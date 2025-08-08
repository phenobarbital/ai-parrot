"""
FlowtaskTool for AI-Parrot - Execute Flowtask components dynamically.

This tool allows AI-Parrot agents to run Flowtask components with dynamic
input data and return structured results.
"""
from typing import Any, Dict, List, Optional, Union, Type
import importlib
from pydantic import BaseModel, Field
import pandas as pd
from ..abstract import AbstractTool, ToolResult


class FlowtaskInput(BaseModel):
    """Input schema for FlowtaskTool."""

    component_name: str = Field(
        description="Name of the Flowtask component to execute (e.g., 'GooglePlaces', 'GoogleGeoCoding')"
    )

    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary of attributes to pass to the component (e.g., {'use_proxies': True, 'type': 'traffic'})"
    )

    input_data: Union[Dict[str, Any], List[Dict[str, Any]], str] = Field(
        description="Input data for the component - can be a dictionary, list of dictionaries, or JSON string"
    )

    structured_output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional structured output schema to format the results"
    )

    return_as_dataframe: bool = Field(
        default=False,
        description="Whether to return the result as a pandas DataFrame (if possible)"
    )


class FlowtaskTool(AbstractTool):
    """
    Tool for executing Flowtask components dynamically.

    This tool can import and run any Flowtask component with custom attributes
    and input data, returning the results in various formats.
    """

    name = "flowtask_execution"
    description = "Execute Flowtask components with custom input data and attributes"
    args_schema = FlowtaskInput

    def __init__(self, **kwargs):
        """Initialize the FlowtaskTool."""
        super().__init__(**kwargs)

        # Component cache to avoid repeated imports
        self._component_cache: Dict[str, Type] = {}

        # Available components (can be extended)
        self.known_components = {
            'GooglePlaces',
        }

    def _import_component(self, component_name: str) -> Type:
        """
        Dynamically import a Flowtask component.

        Args:
            component_name: Name of the component to import

        Returns:
            Component class

        Raises:
            ImportError: If component cannot be imported
        """
        # Check cache first
        if component_name in self._component_cache:
            return self._component_cache[component_name]

        try:
            # Import from flowtask.components
            module_path = f"flowtask.components.{component_name}"
            module = importlib.import_module(module_path)
            component_class = getattr(module, component_name)

            # Cache the component
            self._component_cache[component_name] = component_class

            self.logger.debug(
                f"Successfully imported component: {component_name}"
            )
            return component_class

        except ImportError as e:
            error_msg = f"Could not import component '{component_name}': {str(e)}"
            self.logger.error(error_msg)
            raise ImportError(error_msg)

        except AttributeError as e:
            error_msg = f"Component '{component_name}' not found in module: {str(e)}"
            self.logger.error(error_msg)
            raise ImportError(error_msg)

    def _prepare_input_data(self, input_data: Union[Dict, List, str]) -> Union[pd.DataFrame, Dict, List]:
        """
        Prepare input data for the component.

        Args:
            input_data: Raw input data

        Returns:
            Processed input data (DataFrame, dict, or list)
        """
        try:
            # Handle string input (assume JSON)
            if isinstance(input_data, str):
                input_data = self._json.loads(input_data)

            # Convert list of dictionaries to DataFrame
            if isinstance(input_data, list) and len(input_data) > 0:
                if isinstance(input_data[0], dict):
                    return pd.DataFrame(input_data)
                else:
                    return input_data

            # Convert dictionary to DataFrame if it has list values
            if isinstance(input_data, dict):
                # Check if it's suitable for DataFrame conversion
                if all(isinstance(v, list) for v in input_data.values()):
                    try:
                        return pd.DataFrame(input_data)
                    except ValueError:
                        # If DataFrame conversion fails, return as dict
                        return input_data
                else:
                    # Single row dictionary - convert to DataFrame
                    return pd.DataFrame([input_data])

            return input_data

        except Exception as e:
            self.logger.warning(
                f"Could not process input data: {str(e)}"
            )
            return input_data

    def _format_output(
        self,
        result: Any,
        structured_output: Optional[Dict[str, Any]] = None,
        return_as_dataframe: bool = False
    ) -> Any:
        """
        Format the component output according to specifications.

        Args:
            result: Raw component result
            structured_output: Optional output structure
            return_as_dataframe: Whether to return as DataFrame

        Returns:
            Formatted result
        """
        try:
            # If result is already a DataFrame and return_as_dataframe is True
            if isinstance(result, pd.DataFrame):
                if return_as_dataframe:
                    # Convert DataFrame to serializable format
                    return {
                        "data": result.to_dict(orient='records'),
                        "columns": list(result.columns),
                        "shape": result.shape,
                        "type": "dataframe"
                    }
                else:
                    # Convert to list of dictionaries
                    return result.to_dict(orient='records')

            # If result is a list and we want DataFrame format
            if isinstance(result, list) and return_as_dataframe:
                if result and isinstance(result[0], dict):
                    df = pd.DataFrame(result)
                    return {
                        "data": result,
                        "columns": list(df.columns),
                        "shape": df.shape,
                        "type": "dataframe"
                    }

            # Apply structured output if specified
            if structured_output:
                return self._apply_structured_output(
                    result,
                    structured_output
                )

            return result

        except Exception as e:
            self.logger.warning(
                f"Could not format output: {str(e)}"
            )
            return result

    def _apply_structured_output(self, result: Any, structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply structured output formatting to the result.

        Args:
            result: Raw result data
            structure: Desired output structure

        Returns:
            Structured result
        """
        try:
            if isinstance(result, pd.DataFrame):
                data = result.to_dict(orient='records')
            elif isinstance(result, list):
                data = result
            else:
                data = [result] if not isinstance(result, list) else result

            # Apply the structure mapping
            structured_result = {}
            for key, mapping in structure.items():
                if isinstance(mapping, str):
                    # Simple field mapping
                    if isinstance(data, list) and data:
                        structured_result[key] = [item.get(mapping) for item in data if isinstance(item, dict)]
                    else:
                        structured_result[key] = data.get(mapping) if isinstance(data, dict) else None
                elif isinstance(mapping, dict):
                    # Nested structure
                    structured_result[key] = self._apply_structured_output(data, mapping)
                else:
                    structured_result[key] = mapping

            return structured_result

        except Exception as e:
            self.logger.warning(
                f"Could not apply structured output: {str(e)}"
            )
            return result

    async def _execute(self, **kwargs) -> ToolResult:
        """
        Execute a Flowtask component with the provided parameters.

        Args:
            **kwargs: Tool arguments matching FlowtaskInput schema

        Returns:
            ToolResult with component execution results
        """
        try:
            # Extract parameters
            component_name = kwargs['component_name']
            attributes = kwargs.get('attributes', {})
            input_data = kwargs['input_data']
            structured_output = kwargs.get('structured_output')
            return_as_dataframe = kwargs.get('return_as_dataframe', False)

            self.logger.debug(
                f"Executing Flowtask component: {component_name}"
            )

            # Import the component
            component_cls = self._import_component(component_name)

            # Prepare input data
            processed_input = self._prepare_input_data(input_data)

            # Create component instance with attributes
            component_kwargs = attributes.copy()
            component_kwargs['input'] = processed_input
            try:
                component = component_cls(**component_kwargs)
            except TypeError as e:
                error_msg = f"Failed to initialize component '{component_name}': {str(e)}"
                self.logger.error(error_msg)
                return ToolResult(
                    status="error",
                    result=None,
                    error=error_msg,
                    metadata={"component_name": component_name}
                )

            # Execute the component using async context manager
            async with component as comp:
                self.logger.debug(
                    f"Running component {component_name} with attributes: {attributes}"
                )
                result = await comp.run()

                # Format the output
                formatted_result = self._format_output(
                    result,
                    structured_output,
                    return_as_dataframe
                )

                self.logger.info(
                    f"Component {component_name} executed successfully"
                )

                return ToolResult(
                    status="success",
                    result=formatted_result,
                    metadata={
                        "component_name": component_name,
                        "attributes": attributes,
                        "input_type": type(processed_input).__name__,
                        "output_type": type(result).__name__,
                        "structured_output_applied": structured_output is not None,
                        "returned_as_dataframe": return_as_dataframe
                    }
                )

        except ImportError as e:
            error_msg = f"Failed to import component '{component_name}': {str(e)}"
            self.logger.error(error_msg)
            return ToolResult(
                status="error",
                result=None,
                error=error_msg,
                metadata={"component_name": component_name}
            )

        except Exception as e:
            error_msg = f"Failed to execute component '{component_name}': {str(e)}"
            self.logger.error(error_msg)

            return ToolResult(
                status="error",
                result=None,
                error=error_msg,
                metadata={
                    "component_name": component_name,
                    "attributes": attributes,
                    "error_type": type(e).__name__
                }
            )

    def list_known_components(self) -> List[str]:
        """
        Get a list of known Flowtask components.

        Returns:
            List of component names
        """
        return sorted(list(self.known_components))

    def add_known_component(self, component_name: str) -> None:
        """
        Add a component to the known components list.

        Args:
            component_name: Name of the component to add
        """
        self.known_components.add(component_name)
        self.logger.info(f"Added component to known list: {component_name}")

    def clear_component_cache(self) -> None:
        """Clear the component import cache."""
        self._component_cache.clear()
        self.logger.info("Component cache cleared")
