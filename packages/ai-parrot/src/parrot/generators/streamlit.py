from typing import Type, List
import ast
from pydantic import BaseModel, Field
from .base import WebAppGenerator


class StreamlitApp(BaseModel):
    """Pydantic schema for Streamlit application output."""
    code: str = Field(description="Complete Streamlit Python code")
    title: str = Field(description="App title")
    description: str = Field(description="Brief description of the app")
    requirements: List[str] = Field(
        description="Python package requirements",
        default_factory=lambda: ["streamlit"]
    )
    features: List[str] = Field(description="List of main features")


class StreamlitGenerator(WebAppGenerator):
    """Generator for Streamlit applications."""

    def get_system_prompt(self) -> str:
        return """You are an expert Streamlit developer creating production-ready applications.

**User Requirements:**
{user_description}

{additional_requirements}

**Technical Specifications:**
- Streamlit version: 1.28+
- Python 3.10+
- Use st.cache_data for expensive computations
- Implement proper error handling with try-except blocks
- Add loading states with st.spinner()
- Use st.session_state for state management
- Add input validation and clear error messages

**Design Guidelines:**
- Clean, modern UI with st.columns for layout
- Consistent spacing with st.divider() and padding
- Helpful tooltips using help parameter
- Clear section headers with st.header() and st.subheader()
- Data export functionality where appropriate
- Mobile-responsive considerations

**Code Structure:**
1. Required imports at the top
2. Page configuration using st.set_page_config() with appropriate title and layout
3. Helper functions decorated with @st.cache_data where appropriate
4. Main application logic
5. if __name__ == "__main__": block at the end

**Quality Standards:**
- All functions must have docstrings
- Use type hints for function parameters
- Include comments for complex logic
- Handle edge cases and errors gracefully
- Use st.empty() for dynamic content updates
- Add st.success(), st.warning(), st.error() for user feedback

**Example of Expected Quality:**
{high_quality_example}

Generate a complete, production-ready Streamlit application now."""

    def get_output_schema(self) -> Type[BaseModel]:
        return StreamlitApp

    def get_examples(self) -> str:
        return '''
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Data Analysis Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Cache expensive operations
@st.cache_data
def load_data() -> pd.DataFrame:
    """Load and prepare sample data."""
    return pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=100),
        'category': ['A', 'B', 'C', 'D'] * 25,
        'value': np.random.randint(10, 100, 100)
    })

@st.cache_data
def calculate_metrics(df: pd.DataFrame) -> dict:
    """Calculate summary metrics."""
    return {
        'total': df['value'].sum(),
        'average': df['value'].mean(),
        'max': df['value'].max(),
        'min': df['value'].min()
    }

def main():
    """Main application function."""
    st.title("📊 Data Analysis Dashboard")
    st.markdown("Analyze your data with interactive visualizations")

    # Sidebar controls
    with st.sidebar:
        st.header("Filters")
        categories = st.multiselect(
            "Select Categories",
            options=['A', 'B', 'C', 'D'],
            default=['A', 'B'],
            help="Choose which categories to display"
        )

    # Load data
    try:
        with st.spinner("Loading data..."):
            df = load_data()

        # Filter data
        filtered_df = df[df['category'].isin(categories)]

        if filtered_df.empty:
            st.warning("No data available for selected filters")
            return

        # Metrics row
        metrics = calculate_metrics(filtered_df)
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total", f"{metrics['total']:,.0f}")
        with col2:
            st.metric("Average", f"{metrics['average']:.1f}")
        with col3:
            st.metric("Maximum", metrics['max'])
        with col4:
            st.metric("Minimum", metrics['min'])

        st.divider()

        # Visualization
        st.subheader("Trend Analysis")
        fig = px.line(
            filtered_df,
            x='date',
            y='value',
            color='category',
            title='Values Over Time'
        )
        st.plotly_chart(fig, use_container_width=True)

        # Data table
        with st.expander("View Raw Data"):
            st.dataframe(filtered_df, use_container_width=True)

            # Export functionality
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"data_export_{datetime.now():%Y%m%d}.csv",
                mime="text/csv"
            )

        st.success("✓ Analysis complete!")

    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        st.exception(e)

if __name__ == "__main__":
    main()
'''

    def validate_output(self, code: str) -> dict:
        """Validate Python syntax of generated Streamlit code."""
        errors = []
        warnings = []

        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")

        # Check for required Streamlit imports
        if 'import streamlit' not in code:
            warnings.append("Missing streamlit import")

        # Check for page config
        if 'st.set_page_config' not in code:
            warnings.append("Missing st.set_page_config() - recommended for better UX")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
