import sys
from pathlib import Path
import matplotlib

# Ensure we are testing the local package
sys.path.insert(0, str(Path(__file__).parent.parent))

from parrot.tools.pythonrepl import PythonREPLTool

def verify_lazy_loading():
    print("Instantiating PythonREPLTool...")
    tool = PythonREPLTool()
    
    print("Checking locals for lazy-loaded libraries...")
    expected_libs = ['sns', 'folium', 'altair', 'px', 'go', 'pio', 'numexpr', 'bokeh', 'hv']
    missing = []
    for lib in expected_libs:
        if lib not in tool.locals:
            missing.append(lib)
    
    if missing:
        print(f"❌ Missing libraries in locals: {missing}")
        sys.exit(1)
    else:
        print("✅ All expected libraries found in locals.")

    print("Checking matplotlib backend...")
    backend = matplotlib.get_backend()
    if backend.lower() != 'agg':
         # It might be 'module://matplotlib_inline.backend_inline' or similar depending on environment, 
         # but we explicitly set it to Agg in _setup_charts.
         # Actually _setup_charts sets it.
         print(f"⚠️ Matplotlib backend is '{backend}', expected 'Agg'. checking tool internal setup...")
         # Inside the tool execution it should be Agg?
         # The tool sets it globally for the process in _setup_charts.
    else:
        print("✅ Matplotlib backend is Agg.")

    print("Executing code using seaborn...")
    try:
        result = tool.execute_sync("import seaborn as sns; print(f'Seaborn version: {sns.__version__}')")
        print(f"Execution Result:\n{result}")
        if "Seaborn version" not in result:
             print("❌ Execution failed to produce expected output.")
             sys.exit(1)
        else:
             print("✅ Seaborn execution successful.")
    except Exception as e:
        print(f"❌ Execution failed with error: {e}")
        sys.exit(1)

    print("Executing code using holoviews...")
    try:
        result = tool.execute_sync("import holoviews as hv; print(f'HoloViews version: {hv.__version__}')")
        print(f"Execution Result:\n{result}")
        if "HoloViews version" not in result:
             print("❌ HoloViews execution failed.")
             sys.exit(1)
        else:
             print("✅ HoloViews execution successful.")
    except Exception as e:
        print(f"❌ Execution failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_lazy_loading()
