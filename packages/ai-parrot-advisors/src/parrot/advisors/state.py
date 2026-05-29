# parrot/advisors/state.py
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from dataclasses import dataclass, field


class SelectionPhase(str, Enum):
    """Phases of the product selection wizard."""
    IDLE = "idle"              # No active selection
    INTAKE = "intake"          # Just started, loading products
    QUESTIONING = "questioning"  # Asking discriminant questions
    NARROWING = "narrowing"    # Few products left, more specific questions
    COMPARISON = "comparison"  # 2-3 products, showing side-by-side
    RECOMMENDATION = "recommendation"  # 1 product, final recommendation
    COMPLETED = "completed"    # User accepted/rejected recommendation


class SelectionState(BaseModel):
    """
    Current state of product selection.
    
    This is what gets stored in Redis and snapshotted for Memento.
    """
    # Identity
    session_id: str
    user_id: str
    catalog_id: str = "default"
    
    # Phase tracking
    phase: SelectionPhase = SelectionPhase.IDLE
    
    # Criteria collected from user
    criteria: Dict[str, Any] = Field(default_factory=dict)
    
    # Product tracking
    all_product_ids: List[str] = Field(default_factory=list)  # Original set
    candidate_ids: List[str] = Field(default_factory=list)    # Current candidates
    eliminated: Dict[str, str] = Field(default_factory=dict)  # {product_id: reason}
    
    # Question tracking
    questions_asked: List[str] = Field(default_factory=list)
    current_question: Optional[str] = None
    pending_questions: List[str] = Field(default_factory=list)
    
    # Timestamps
    started_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @property
    def products_remaining(self) -> int:
        return len(self.candidate_ids)
    
    @property
    def products_eliminated(self) -> int:
        return len(self.all_product_ids) - len(self.candidate_ids)
    
    def should_recommend(self) -> bool:
        """Check if we should move to recommendation phase."""
        return self.products_remaining <= 3


@dataclass
class StateSnapshot:
    """
    Memento: Immutable snapshot of SelectionState.
    
    Used for undo/redo functionality.
    """
    state: SelectionState
    timestamp: datetime = field(default_factory=datetime.utcnow)
    action: str = ""  # What action led to this state
    question_answered: Optional[str] = None
    answer_given: Optional[str] = None
    
    @classmethod
    def from_state(
        cls, 
        state: SelectionState, 
        action: str = "",
        question: str = None,
        answer: str = None
    ) -> "StateSnapshot":
        """Create snapshot from current state (deep copy)."""
        return cls(
            state=state.model_copy(deep=True),
            action=action,
            question_answered=question,
            answer_given=answer
        )


class SelectionHistory(BaseModel):
    """
    Memento Caretaker: Manages state history for undo/redo.
    
    Stored alongside SelectionState in Redis.
    """
    snapshots: List[Dict[str, Any]] = Field(default_factory=list)  # Serialized StateSnapshots
    current_index: int = -1  # Position in history (-1 = no history)
    max_history: int = 20    # Maximum snapshots to keep
    
    def push(self, snapshot: StateSnapshot) -> None:
        """Add a new snapshot (discards any redo history)."""
        # Truncate any "future" states if we're not at the end
        if self.current_index < len(self.snapshots) - 1:
            self.snapshots = self.snapshots[:self.current_index + 1]
        
        # Add new snapshot
        self.snapshots.append({
            "state": snapshot.state.model_dump(),
            "timestamp": snapshot.timestamp.isoformat(),
            "action": snapshot.action,
            "question_answered": snapshot.question_answered,
            "answer_given": snapshot.answer_given
        })
        
        # Trim if exceeds max
        if len(self.snapshots) > self.max_history:
            self.snapshots = self.snapshots[-self.max_history:]
        
        self.current_index = len(self.snapshots) - 1
    
    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return self.current_index > 0
    
    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return self.current_index < len(self.snapshots) - 1
    
    def undo(self) -> Optional[StateSnapshot]:
        """Go back one step, return the previous state."""
        if not self.can_undo():
            return None
        self.current_index -= 1
        return self._get_current_snapshot()
    
    def redo(self) -> Optional[StateSnapshot]:
        """Go forward one step, return the next state."""
        if not self.can_redo():
            return None
        self.current_index += 1
        return self._get_current_snapshot()
    
    def _get_current_snapshot(self) -> StateSnapshot:
        """Reconstruct StateSnapshot from stored dict."""
        data = self.snapshots[self.current_index]
        return StateSnapshot(
            state=SelectionState(**data["state"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            action=data["action"],
            question_answered=data["question_answered"],
            answer_given=data["answer_given"]
        )
    
    def get_history_summary(self) -> List[Dict[str, Any]]:
        """Get human-readable history for display."""
        return [
            {
                "step": i + 1,
                "action": s["action"],
                "question": s["question_answered"],
                "answer": s["answer_given"],
                "is_current": i == self.current_index
            }
            for i, s in enumerate(self.snapshots)
        ]