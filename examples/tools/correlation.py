import asyncio
import json
from pathlib import Path
import pandas as pd
import numpy as np
from parrot.tools.correlationanalysis import (
    CorrelationAnalysisTool,
    OutputFormat,
    CorrelationMethod
)


# Example usage and testing
async def example_usage():
    """Example of how to use the CorrelationAnalysisTool."""
    # Create sample sales and foot traffic data
    np.random.seed(42)
    dates = pd.date_range('2023-01-01', periods=52, freq='W')

    # Simulate foot traffic with some trend and seasonality
    foot_traffic = 1000 + np.random.normal(0, 100, 52) + np.sin(np.arange(52) * 2 * np.pi / 52) * 200

    # Sales correlated with foot traffic + some noise
    sales = foot_traffic * 0.8 + np.random.normal(0, 50, 52)

    # Census/demographic data (some correlated, some not)
    sample_data = {
        'date': dates,
        'sales': sales,
        'foot_traffic': foot_traffic,
        'avg_age': 35 + np.random.normal(0, 5, 52),
        'income_median': 50000 + np.random.normal(0, 5000, 52),
        'population_density': 2000 + np.random.normal(0, 200, 52),
        'temperature': 20 + 15 * np.sin(np.arange(52) * 2 * np.pi / 52) + np.random.normal(0, 3, 52),
        'marketing_spend': np.random.exponential(500, 52),
        'competitor_stores': np.random.poisson(3, 52),
        'unemployment_rate': 5 + np.random.normal(0, 0.5, 52)
    }

    # Add some correlation between sales and marketing spend
    sample_data['sales'] = sample_data['sales'] + sample_data['marketing_spend'] * 0.1

    df = pd.DataFrame(sample_data)

    # Initialize the tool
    tool = CorrelationAnalysisTool(
        output_dir="./static/correlation_analysis",
        base_url="http://localhost:8000/static"
    )

    # Test 1: Analyze all correlations with sales
    print("=== Test 1: Sales vs All Variables ===")
    result1 = await tool.execute(
        dataframe=df,
        key_column="sales",
        output_format=OutputFormat.ALL,
        min_correlation_threshold=0.1,
        filename="sales_correlations"
    )
    print(f"Status: {result1.status}")
    print(f"Key column: {result1.result['key_column']}")
    print(f"Valid correlations: {result1.result['valid_correlations_count']}")
    print(f"Strongest positive: {result1.result['analysis_summary']['highest_positive_correlation']}")
    print(f"Strongest negative: {result1.result['analysis_summary']['highest_negative_correlation']}")

    # Test 2: Specific columns comparison
    print("\n=== Test 2: Foot Traffic vs Demographics ===")
    demographic_columns = ['avg_age', 'income_median', 'population_density', 'unemployment_rate']
    result2 = await tool.execute(
        dataframe=df,
        key_column="foot_traffic",
        comparison_columns=demographic_columns,
        correlation_method=CorrelationMethod.SPEARMAN,
        output_format=OutputFormat.JSON,
        sort_by_correlation=True
    )
    print(f"Status: {result2.status}")
    print("JSON correlations:")
    for item in result2.result['json_output']['sorted_correlations']:
        print(f"  {item['column']}: {item['correlation']:.3f}")

    # Test 3: Only heatmap output
    print("\n=== Test 3: Marketing Spend Heatmap ===")
    result3 = await tool.execute(
        dataframe=df,
        key_column="marketing_spend",
        output_format=OutputFormat.HEATMAP,
        heatmap_style="viridis",
        figure_size=(12, 6)
    )
    print(f"Status: {result3.status}")

    # Check if heatmap was generated and show how to access it.
    # FEAT-423: matplotlib base64 PNG output was replaced with Vega-Lite
    # JSON specs — heatmap_image/bar_chart_image -> heatmap_vegalite/
    # bar_chart_vegalite. The frontend renders these natively (e.g. via
    # vega-embed); no image decoding is needed.
    heatmap_output = result3.result.get('heatmap_output', {})

    if heatmap_output.get('heatmap_vegalite'):
        heatmap_spec = heatmap_output['heatmap_vegalite']
        print(f"Heatmap generated: Yes (Vega-Lite spec, {len(json.dumps(heatmap_spec))} chars)")

        # Example of how to save the spec for viewing
        try:
            with open('example_heatmap.json', 'w', encoding='utf-8') as f:
                json.dump(heatmap_spec, f, indent=2)
            print("✅ Heatmap Vega-Lite spec saved as 'example_heatmap.json'")
        except Exception as e:
            print(f"❌ Failed to save heatmap: {e}")

        # Show how to embed it client-side (vega-embed)
        print("Embed with: vegaEmbed('#chart', <heatmap_vegalite spec>)")
    else:
        print("Heatmap generated: No")

    if heatmap_output.get('bar_chart_vegalite'):
        bar_chart_spec = heatmap_output['bar_chart_vegalite']
        print(f"Bar chart generated: Yes (Vega-Lite spec, {len(json.dumps(bar_chart_spec))} chars)")

        try:
            with open('example_bar_chart.json', 'w', encoding='utf-8') as f:
                json.dump(bar_chart_spec, f, indent=2)
            print("✅ Bar chart Vega-Lite spec saved as 'example_bar_chart.json'")
        except Exception as e:
            print(f"❌ Failed to save bar chart: {e}")
    else:
        print("Bar chart generated: No")

    # Test 4: Show how to use Vega-Lite specs in different contexts
    print("\n=== Test 4: Vega-Lite Spec Usage Examples ===")
    result4 = await tool.execute(
        dataframe=df,
        key_column="sales",
        comparison_columns=['foot_traffic', 'marketing_spend', 'temperature'],
        output_format=OutputFormat.HEATMAP,
        filename="sales_analysis_heatmap"  # This will save to file
    )

    if result4.status == "success":
        heatmap_data = result4.result.get('heatmap_output', {})

        print("📊 Available chart outputs:")
        print(f"  - Heatmap Vega-Lite spec: {'✅' if heatmap_data.get('heatmap_vegalite') else '❌'}")
        print(f"  - Bar chart Vega-Lite spec: {'✅' if heatmap_data.get('bar_chart_vegalite') else '❌'}")

        if 'file_path' in heatmap_data:
            print(f"  - Saved to file: {heatmap_data['file_path']}")
            print(f"  - File URL: {heatmap_data['file_url']}")
            print(f"  - File size: {heatmap_data['file_size']} bytes")

        # Show how to display in Jupyter notebook
        print("\n💡 Usage in Jupyter Notebook:")
        print("import altair as alt")
        print("")
        print("# Display heatmap (Vega-Lite spec renders natively in Jupyter)")
        print("heatmap_spec = result.result['heatmap_output']['heatmap_vegalite']")
        print("alt.Chart.from_dict(heatmap_spec)")

        # Show how to use in web apps
        print("\n🌐 Usage in Web Applications:")
        print("<!-- HTML: load vega/vega-lite/vega-embed from CDN, then -->")
        print("<div id='heatmap'></div>")
        print("<script>vegaEmbed('#heatmap', {{ heatmap_vegalite_json }});</script>")
        print("")
        print("# Flask/Django template context")
        print("context = {")
        print("    'heatmap_vegalite': result.result['heatmap_output']['heatmap_vegalite'],")
        print("    'bar_chart_vegalite': result.result['heatmap_output']['bar_chart_vegalite']")
        print("}")


# Additional utility functions for working with the Vega-Lite chart specs
def save_correlation_charts(result: dict, output_dir: str = "./") -> dict:
    """
    Save correlation analysis charts (Vega-Lite JSON specs) to files.

    FEAT-423: matplotlib base64 PNG output was replaced with Vega-Lite JSON.

    Args:
        result: Result dictionary from CorrelationAnalysisTool
        output_dir: Directory to save chart specs

    Returns:
        Dictionary with saved file paths
    """
    saved_files = {}
    heatmap_output = result.get('heatmap_output', {})

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save heatmap
    if heatmap_output.get('heatmap_vegalite'):
        heatmap_file = output_path / "correlation_heatmap.json"
        with open(heatmap_file, 'w', encoding='utf-8') as f:
            json.dump(heatmap_output['heatmap_vegalite'], f, indent=2)
        saved_files['heatmap'] = str(heatmap_file)

    # Save bar chart
    if heatmap_output.get('bar_chart_vegalite'):
        bar_chart_file = output_path / "correlation_bar_chart.json"
        with open(bar_chart_file, 'w', encoding='utf-8') as f:
            json.dump(heatmap_output['bar_chart_vegalite'], f, indent=2)
        saved_files['bar_chart'] = str(bar_chart_file)

    return saved_files


def create_html_report(result: dict, title: str = "Correlation Analysis Report") -> str:
    """
    Create an HTML report with correlation analysis results.

    FEAT-423: charts embed as interactive Vega-Lite specs (rendered
    client-side via vega-embed) instead of base64 PNG <img> tags.

    Args:
        result: Result dictionary from CorrelationAnalysisTool
        title: Title for the HTML report

    Returns:
        HTML string containing the complete report
    """
    html_parts = []

    # HTML header — includes the vega/vega-lite/vega-embed CDN scripts
    # needed to render the embedded Vega-Lite specs below.
    html_parts.append(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
        <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
        <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1, h2 {{ color: #333; }}
            .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            .correlation-table {{ border-collapse: collapse; width: 100%; }}
            .correlation-table th, .correlation-table td {{ border: 1px solid #ddd; padding: 8px; }}
            .correlation-table th {{ background-color: #f2f2f2; }}
            .chart-container {{ text-align: center; margin: 20px 0; }}
        </style>
    </head>
    <body>
    <h1>{title}</h1>
    """)

    # Analysis summary
    if 'analysis_summary' in result:
        summary = result['analysis_summary']
        html_parts.append(f"""
        <div class="summary">
            <h2>Analysis Summary</h2>
            <p><strong>Key Column:</strong> {result.get('key_column', 'N/A')}</p>
            <p><strong>Correlation Method:</strong> {result.get('correlation_method', 'N/A')}</p>
            <p><strong>Comparisons Made:</strong> {result.get('comparison_columns_count', 0)}</p>
            <p><strong>Valid Correlations:</strong> {result.get('valid_correlations_count', 0)}</p>
            <p><strong>Strongest Positive:</strong> {summary.get('highest_positive_correlation', {}).get('column', 'N/A')}
               ({summary.get('highest_positive_correlation', {}).get('value', 0):.3f})</p>
            <p><strong>Strongest Negative:</strong> {summary.get('highest_negative_correlation', {}).get('column', 'N/A')}
               ({summary.get('highest_negative_correlation', {}).get('value', 0):.3f})</p>
        </div>
        """)

    # Correlation table
    if 'dataframe_output' in result:
        html_parts.append("<h2>Correlation Results</h2>")
        html_parts.append(result['dataframe_output'].get('dataframe_html', ''))

    # Charts — embedded as Vega-Lite specs, rendered client-side.
    # Note: spec values are escaped ('<' -> '\\u003c') before embedding in
    # the <script> block, mirroring QuickEdaTool._altair_chart_to_html —
    # a value containing '</script>' could otherwise break out of the
    # script context.
    heatmap_output = result.get('heatmap_output', {})
    if heatmap_output.get('heatmap_vegalite'):
        spec_json = json.dumps(heatmap_output['heatmap_vegalite']).replace("<", "\\u003c")
        html_parts.append(f"""
        <h2>Correlation Heatmap</h2>
        <div class="chart-container">
            <div id="heatmap-chart"></div>
            <script>vegaEmbed('#heatmap-chart', {spec_json}).catch(console.error);</script>
        </div>
        """)

    if heatmap_output.get('bar_chart_vegalite'):
        spec_json = json.dumps(heatmap_output['bar_chart_vegalite']).replace("<", "\\u003c")
        html_parts.append(f"""
        <h2>Correlation Bar Chart</h2>
        <div class="chart-container">
            <div id="bar-chart"></div>
            <script>vegaEmbed('#bar-chart', {spec_json}).catch(console.error);</script>
        </div>
        """)

    # HTML footer
    html_parts.append("</body></html>")

    return "\n".join(html_parts)


if __name__ == "__main__":
    asyncio.run(example_usage())
