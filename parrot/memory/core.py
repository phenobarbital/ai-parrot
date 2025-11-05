# ai_parrot/memory/agent_core_memory.py

import asyncio
import pickle
import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from uuid import uuid4
from pathlib import Path
import redis.asyncio as redis
import numpy as np
from sentence_transformers import SentenceTransformer
from bm25s import BM25
from transformers import pipeline
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from navconfig import BASE_DIR


@dataclass
class MemoryEntry:
    """Memory Entry structure."""
    id: str
    query: str
    response_summary: str
    tools_used: List[str]
    outcome: str
    embedding: np.ndarray
    metadata: Dict
    timestamp: datetime
    access_count: int = 0
    source: str = "memory"  # for ranking
    score: float = 0.0
    final_score: float = 0.0


class ValueScorer:
    """Heurísticas para determinar valor de una interacción"""

    @staticmethod
    def score_interaction(
        query: str,
        response: str,
        tools_used: List[str],
        outcome: str,
        user_feedback: Optional[str] = None
    ) -> float:
        score = 0.0

        # Outcome positivo
        if outcome in {'resolved', 'successful'}:
            score += 0.3

        # Usó herramientas (no fue solo conversacional)
        if tools_used:
            score += 0.2

        # Query substantiva
        if len(query.split()) > 5:
            score += 0.1

        # Respuesta substantiva
        if len(response) > 100:
            score += 0.2

        # Feedback explícito del usuario
        if user_feedback == 'positive':
            score += 0.3
        elif user_feedback == 'negative':
            score -= 0.2

        return max(0.0, min(score, 1.0))

    @staticmethod
    def is_valuable(score: float) -> bool:
        return score >= 0.4  # threshold ajustable


class AgentCoreMemory:
    """
    Memoria compartida híbrida: Redis (hot) + PgVector (cold)
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        pgvector_store,  # tu implementación actual de PgVector
        embedder_model: str = "all-MiniLM-L6-v2",
        summarizer_model: str = "facebook/bart-large-cnn",
        redis_ttl_days: int = 7,
        distill_schedule_hours: int = 24
    ):
        self.redis = redis_client
        self.pgvector = pgvector_store

        # Embeddings
        self.embedder = SentenceTransformer(embedder_model)

        # Summarization
        self.summarizer = pipeline(
            "summarization",
            model=summarizer_model,
            device=0 if self._has_gpu() else -1
        )

        # BM25 search (lo construimos lazy)
        self._bm25_index: Dict[str, BM25] = {}  # {agent_type: BM25}
        self.bm25_cache_dir = Path(BASE_DIR) / "cache" / "bm25"
        self.bm25_cache_dir.mkdir(parents=True, exist_ok=True)

        # Config
        self.redis_ttl = redis_ttl_days * 24 * 3600

        # Agent registry
        self.agent_registry: Dict[str, Dict] = {}

        # Scheduler para destilación periódica
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self._distillation_job,
            'interval',
            hours=distill_schedule_hours,
            id='memory_distillation'
        )
        # load bm25 indexes on startup:
        self._load_bm25_indices()

    def _get_bm25_cache_path(self, agent_type: str) -> Path:
        return self.bm25_cache_dir / f"{agent_type}_bm25.pkl"

    def _load_bm25_indices(self):
        """Carga índices BM25 desde disco al inicio"""
        for agent_type in self.agent_registry.keys():
            cache_path = self._get_bm25_cache_path(agent_type)
            if cache_path.exists():
                try:
                    with open(cache_path, 'rb') as f:
                        self._bm25_index[agent_type] = pickle.load(f)
                    print(f"[BM25] Loaded index for {agent_type}")
                except Exception as e:
                    print(f"[BM25] Failed to load index for {agent_type}: {e}")

    async def _save_bm25_index(self, agent_type: str):
        """Persiste índice BM25 a disco"""
        if agent_type not in self._bm25_index:
            return

        cache_path = self._get_bm25_cache_path(agent_type)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(self._bm25_index[agent_type], f)
            print(f"[BM25] Saved index for {agent_type}")
        except Exception as e:
            print(f"[BM25] Failed to save index for {agent_type}: {e}")

    async def _rebuild_and_save_bm25(self, agent_type: str):
        """Reconstruye y persiste BM25 index"""
        # Fetch todas las memorias
        pattern = f"agentcore:{agent_type}:memory:*"
        texts = []

        async for key in self.redis.scan_iter(match=pattern):
            data = await self.redis.hgetall(key)
            if data and b'query' in data:
                texts.append(data[b'query'].decode())

        if texts:
            # Rebuild index
            self._bm25_index[agent_type] = BM25()
            self._bm25_index[agent_type].index(texts)

            # Save to disk
            await self._save_bm25_index(agent_type)

    def start(self):
        """Inicia el scheduler de destilación"""
        self.scheduler.start()

    def shutdown(self):
        """Detiene el scheduler"""
        self.scheduler.shutdown()

    def register_agent_expertise(
        self,
        agent_type: str,
        expertise_domains: List[str],
        expertise_description: str
    ):
        """Registra dominios de experiencia de un agente"""
        self.agent_registry[agent_type] = {
            'domains': expertise_domains,
            'description': expertise_description,
            'embedding': self.embedder.encode(expertise_description)
        }

    # ==================== WRITE: Store Memory ====================

    async def store_interaction(
        self,
        agent_type: str,
        query: str,
        response: str,
        tools_used: List[str] = None,
        outcome: str = 'unknown',
        user_feedback: Optional[str] = None,
        metadata: Dict = None
    ) -> Optional[str]:
        """
        Almacena una interacción en Redis si es valiosa

        Returns:
            memory_id si se almacenó, None si se descartó
        """
        tools_used = tools_used or []
        metadata = metadata or {}

        # 1. Evaluar valor
        value_score = ValueScorer.score_interaction(
            query=query,
            response=response,
            tools_used=tools_used,
            outcome=outcome,
            user_feedback=user_feedback
        )

        if not ValueScorer.is_valuable(value_score):
            return None  # Descartamos interacción de bajo valor

        # 2. Generar embedding
        embedding = self.embedder.encode(query)

        # 3. Crear memory entry
        memory_id = str(uuid4())
        key = f"agentcore:{agent_type}:memory:{memory_id}"

        # 4. Summarizar respuesta si es muy larga
        response_summary = response
        if len(response) > 500:
            response_summary = await self._summarize_text(response, max_length=150)

        memory_data = {
            "id": memory_id,
            "query": query,
            "response_summary": response_summary,
            "tools_used": json.dumps(tools_used),
            "outcome": outcome,
            "embedding": pickle.dumps(embedding),
            "metadata": json.dumps(metadata),
            "timestamp": datetime.utcnow().isoformat(),
            "access_count": 0,
            "value_score": value_score
        }

        # 5. Store en Redis con TTL
        await self.redis.hset(key, mapping=memory_data)
        await self.redis.expire(key, self.redis_ttl)

        # Invalidar BM25 index para reconstruir
        if agent_type in self._bm25_index:
            del self._bm25_index[agent_type]

        # Trigger rebuild y save en background
        asyncio.create_task(
            self._rebuild_and_save_bm25(agent_type)
        )

        return memory_id

    # ==================== READ: Retrieve Memory ====================

    async def retrieve_memory(
        self,
        query: str,
        agent_type: str,
        top_k: int = 5,
        include_cross_domain: bool = True
    ) -> List[MemoryEntry]:
        """
        Recupera memorias relevantes usando búsqueda híbrida
        BM25 (lexical) + Semantic (embeddings)
        """
        # 1. Determinar agent types relevantes
        agent_types = [agent_type]
        if include_cross_domain:
            cross_agents = await self._route_cross_domain(query, agent_type)
            agent_types.extend(cross_agents)

        # 2. Búsqueda híbrida por cada agent type
        all_memories = []
        for atype in agent_types:
            memories = await self._hybrid_search(
                query=query,
                agent_type=atype,
                top_k=20  # Recuperamos más para re-ranking
            )

            # Aplicar decay si es cross-domain
            decay_factor = 1.0 if atype == agent_type else 0.6
            for mem in memories:
                mem.source = "memory_same" if atype == agent_type else "memory_cross"
                mem.score *= decay_factor

            all_memories.extend(memories)

        # 3. Re-ranking final
        ranked_memories = self._rerank_memories(all_memories)

        # 4. Actualizar access_count en Redis (para LRU)
        await self._update_access_counts(ranked_memories[:top_k])

        return ranked_memories[:top_k]

    async def _hybrid_search(
        self,
        query: str,
        agent_type: str,
        top_k: int = 20
    ) -> List[MemoryEntry]:
        """Búsqueda híbrida: BM25 + Semantic"""

        # Fetch todas las memorias de este agent_type
        pattern = f"agentcore:{agent_type}:memory:*"
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key)

        if not keys:
            return []

        # Fetch datos en batch
        pipeline = self.redis.pipeline()
        for key in keys:
            pipeline.hgetall(key)
        results = await pipeline.execute()

        memories = []
        texts = []
        embeddings = []

        for key, data in zip(keys, results):
            if not data:
                continue

            mem = MemoryEntry(
                id=data[b'id'].decode(),
                query=data[b'query'].decode(),
                response_summary=data[b'response_summary'].decode(),
                tools_used=json.loads(data[b'tools_used']),
                outcome=data[b'outcome'].decode(),
                embedding=pickle.loads(data[b'embedding']),
                metadata=json.loads(data[b'metadata']),
                timestamp=datetime.fromisoformat(data[b'timestamp'].decode()),
                access_count=int(data[b'access_count'])
            )

            memories.append(mem)
            texts.append(mem.query)
            embeddings.append(mem.embedding)

        if not memories:
            return []

        # Stage 1: BM25 scoring
        bm25_scores = await self._bm25_score(query, texts, agent_type)

        # Stage 2: Semantic scoring
        query_embedding = self.embedder.encode(query)
        semantic_scores = [
            self._cosine_similarity(query_embedding, emb)
            for emb in embeddings
        ]

        # Combine scores (40% BM25, 60% Semantic)
        for i, mem in enumerate(memories):
            mem.score = 0.4 * bm25_scores[i] + 0.6 * semantic_scores[i]

        # Sort y return top_k
        memories.sort(key=lambda x: x.score, reverse=True)
        return memories[:top_k]

    async def _bm25_score(
        self,
        query: str,
        corpus_texts: List[str],
        agent_type: str
    ) -> List[float]:
        """BM25 scoring usando bm25s"""

        # Lazy build index si no existe
        if agent_type not in self._bm25_index:
            self._bm25_index[agent_type] = BM25()
            self._bm25_index[agent_type].index(corpus_texts)

        scores = self._bm25_index[agent_type].score(query)

        # Normalizar scores a [0, 1]
        if len(scores) > 0:
            max_score = max(scores)
            if max_score > 0:
                scores = [s / max_score for s in scores]

        return scores

    def _rerank_memories(self, memories: List[MemoryEntry]) -> List[MemoryEntry]:
        """
        Re-ranking con source priority:
        - memory_same: score * 0.8
        - memory_cross: score * 0.6
        """
        for mem in memories:
            if mem.source == "memory_same":
                mem.final_score = mem.score * 0.8
            else:  # memory_cross
                mem.final_score = mem.score * 0.6

        return sorted(memories, key=lambda x: x.final_score, reverse=True)

    async def _update_access_counts(self, memories: List[MemoryEntry]):
        """Incrementa access_count para LRU (más accesados sobreviven)"""
        pipeline = self.redis.pipeline()
        for mem in memories:
            key = f"agentcore:{mem.source.split('_')[1] if '_' in mem.source else 'unknown'}:memory:{mem.id}"
            # Buscar el agent_type correcto - esto es un hack, deberíamos almacenarlo
            # Por ahora, buscamos en todos los agent_types registrados
            for agent_type in self.agent_registry.keys():
                potential_key = f"agentcore:{agent_type}:memory:{mem.id}"
                pipeline.hincrby(potential_key, "access_count", 1)

        await pipeline.execute()

    # ==================== ROUTING ====================

    async def _route_cross_domain(
        self,
        query: str,
        current_agent_type: str,
        threshold: float = 0.5
    ) -> List[str]:
        """Routing semántico a otros agent types"""
        query_emb = self.embedder.encode(query)

        relevant_agents = []
        for agent_type, meta in self.agent_registry.items():
            if agent_type == current_agent_type:
                continue

            similarity = self._cosine_similarity(query_emb, meta['embedding'])

            if similarity > threshold:
                relevant_agents.append((agent_type, similarity))

        # Return top 2
        relevant_agents.sort(key=lambda x: x[1], reverse=True)
        return [agent for agent, _ in relevant_agents[:2]]

    # ==================== DISTILLATION ====================

    async def _distillation_job(self):
        """
        Job periódico: mueve memorias antiguas de Redis a PgVector
        """
        print(f"[Distillation] Starting job at {datetime.utcnow()}")

        for agent_type in self.agent_registry.keys():
            await self._distill_agent_memories(agent_type)

        print(f"[Distillation] Job completed")

    async def _distill_agent_memories(self, agent_type: str):
        """
        Identifica memorias antiguas (idle time alto) y las mueve a PgVector
        """
        pattern = f"agentcore:{agent_type}:memory:*"

        # 1. Scan todas las keys
        old_memories = []
        async for key in self.redis.scan_iter(match=pattern):
            # Check idle time (tiempo sin acceso)
            idle_time = await self.redis.object('IDLETIME', key)

            # Si lleva más de 5 días sin acceso, candidato a destilación
            if idle_time and idle_time > (5 * 24 * 3600):
                data = await self.redis.hgetall(key)
                if data:
                    old_memories.append((key, data))

        if not old_memories:
            return

        print(f"[Distillation] Found {len(old_memories)} old memories for {agent_type}")

        # 2. Cluster por similitud (opcional, para agrupar antes de sumarizar)
        # Por simplicidad, lo omitimos en v1 y sumariamos individualmente

        # 3. Summarize y store en PgVector
        for key, data in old_memories:
            try:
                query = data[b'query'].decode()
                response = data[b'response_summary'].decode()

                # Crear un knowledge summary
                combined_text = f"Query: {query}\nResponse: {response}"
                summary = await self._summarize_text(combined_text, max_length=200)

                # Store en PgVector
                await self.pgvector.store(
                    collection=f"agent_longterm_{agent_type}",
                    content=summary,
                    embedding=self.embedder.encode(summary),
                    metadata={
                        'agent_type': agent_type,
                        'source': 'distilled_memory',
                        'original_query': query,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )

                # Delete from Redis
                await self.redis.delete(key)

            except Exception as e:
                print(f"[Distillation] Error processing {key}: {e}")
                continue

        print(f"[Distillation] Distilled {len(old_memories)} memories for {agent_type}")

    # ==================== UTILS ====================

    async def _summarize_text(self, text: str, max_length: int = 150) -> str:
        """Sumariza texto usando BART"""
        try:
            result = self.summarizer(
                text,
                max_length=max_length,
                min_length=30,
                do_sample=False
            )
            return result[0]['summary_text']
        except Exception as e:
            print(f"[Summarization] Error: {e}")
            return text[:max_length]  # Fallback: truncate

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity entre dos vectores"""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    @staticmethod
    def _has_gpu() -> bool:
        """Check si hay GPU disponible"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
