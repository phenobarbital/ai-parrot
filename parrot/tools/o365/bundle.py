"""
SharePoint and OneDrive Toolkits for AI-Parrot

Toolkit wrappers for SharePoint and OneDrive file management tools.
"""
from typing import Dict, Any, Optional, List
from navconfig.logging import logging

from .sharepoint import (
    ListSharePointFilesTool,
    SearchSharePointFilesTool,
    DownloadSharePointFileTool,
    UploadSharePointFileTool
)
from .onedrive import (
    ListOneDriveFilesTool,
    SearchOneDriveFilesTool,
    DownloadOneDriveFileTool,
    UploadOneDriveFileTool
)
from .base import O365AuthMode


class SharePointToolkit:
    """
    SharePoint file management toolkit for AI-Parrot agents.

    This toolkit provides comprehensive SharePoint integration:
    - List files in document libraries
    - Search for files
    - Download files
    - Upload files

    Usage:
        toolkit = SharePointToolkit(
            client_id='your-client-id',
            client_secret='your-client-secret',
            tenant_id='your-tenant-id'
        )

        # Add to agent
        agent = BasicAgent(
            name="SharePointAgent",
            tools=toolkit.get_tools()
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: Optional[str] = None,
        tenant_id: str = None,
        default_auth_mode: str = O365AuthMode.DIRECT,
        scopes: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize SharePoint toolkit.

        Args:
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_id: Azure AD tenant ID
            default_auth_mode: Default authentication mode
            scopes: Custom Graph API scopes
            **kwargs: Additional arguments
        """
        self.logger = logging.getLogger('Parrot.Toolkits.SharePoint')

        # Store credentials
        self.credentials = {
            'client_id': client_id,
            'tenant_id': tenant_id
        }

        if client_secret:
            self.credentials['client_secret'] = client_secret

        self.default_auth_mode = default_auth_mode
        self.scopes = scopes or [
            "Sites.Read.All",
            "Sites.ReadWrite.All",
            "Files.Read.All",
            "Files.ReadWrite.All"
        ]

        # Initialize tools
        self._tools: List[Any] = []
        self._initialize_tools()

        self.logger.info(
            f"SharePointToolkit initialized with {len(self._tools)} tools"
        )

    def _initialize_tools(self):
        """Initialize all SharePoint tools."""
        common_params = {
            'credentials': self.credentials,
            'default_auth_mode': self.default_auth_mode,
            'scopes': self.scopes
        }

        self._tools = [
            ListSharePointFilesTool(**common_params),
            SearchSharePointFilesTool(**common_params),
            DownloadSharePointFileTool(**common_params),
            UploadSharePointFileTool(**common_params)
        ]

        self.logger.debug("Registered SharePoint tools")

    def get_tools(self) -> List[Any]:
        """Get all toolkit tools."""
        return self._tools

    def get_tool_by_name(self, name: str) -> Optional[Any]:
        """Get a specific tool by name."""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    async def cleanup(self):
        """Clean up all tool resources."""
        for tool in self._tools:
            try:
                await tool.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up tool {tool.name}: {e}")

    def __repr__(self) -> str:
        tool_names = [tool.name for tool in self._tools]
        return f"SharePointToolkit(tools={tool_names})"


class OneDriveToolkit:
    """
    OneDrive file management toolkit for AI-Parrot agents.

    This toolkit provides comprehensive OneDrive integration:
    - List files in folders
    - Search for files
    - Download files
    - Upload files

    Usage:
        toolkit = OneDriveToolkit(
            client_id='your-client-id',
            client_secret='your-client-secret',
            tenant_id='your-tenant-id'
        )

        # Add to agent
        agent = BasicAgent(
            name="OneDriveAgent",
            tools=toolkit.get_tools()
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: Optional[str] = None,
        tenant_id: str = None,
        default_auth_mode: str = O365AuthMode.DIRECT,
        scopes: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize OneDrive toolkit.

        Args:
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_id: Azure AD tenant ID
            default_auth_mode: Default authentication mode
            scopes: Custom Graph API scopes
            **kwargs: Additional arguments
        """
        self.logger = logging.getLogger('Parrot.Toolkits.OneDrive')

        # Store credentials
        self.credentials = {
            'client_id': client_id,
            'tenant_id': tenant_id
        }

        if client_secret:
            self.credentials['client_secret'] = client_secret

        self.default_auth_mode = default_auth_mode
        self.scopes = scopes or [
            "Files.Read",
            "Files.ReadWrite",
            "Files.Read.All",
            "Files.ReadWrite.All"
        ]

        # Initialize tools
        self._tools: List[Any] = []
        self._initialize_tools()

        self.logger.info(
            f"OneDriveToolkit initialized with {len(self._tools)} tools"
        )

    def _initialize_tools(self):
        """Initialize all OneDrive tools."""
        common_params = {
            'credentials': self.credentials,
            'default_auth_mode': self.default_auth_mode,
            'scopes': self.scopes
        }

        self._tools = [
            ListOneDriveFilesTool(**common_params),
            SearchOneDriveFilesTool(**common_params),
            DownloadOneDriveFileTool(**common_params),
            UploadOneDriveFileTool(**common_params)
        ]

        self.logger.debug("Registered OneDrive tools")

    def get_tools(self) -> List[Any]:
        """Get all toolkit tools."""
        return self._tools

    def get_tool_by_name(self, name: str) -> Optional[Any]:
        """Get a specific tool by name."""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    async def cleanup(self):
        """Clean up all tool resources."""
        for tool in self._tools:
            try:
                await tool.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up tool {tool.name}: {e}")

    def __repr__(self) -> str:
        tool_names = [tool.name for tool in self._tools]
        return f"OneDriveToolkit(tools={tool_names})"


class Office365FileManagementToolkit:
    """
    Complete Office365 file management toolkit (SharePoint + OneDrive).

    This toolkit bundles both SharePoint and OneDrive tools for
    comprehensive file management across Office365.

    Usage:
        toolkit = Office365FileManagementToolkit(
            client_id='your-client-id',
            client_secret='your-client-secret',
            tenant_id='your-tenant-id'
        )

        agent = BasicAgent(
            name="FileAgent",
            tools=toolkit.get_tools()
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: Optional[str] = None,
        tenant_id: str = None,
        default_auth_mode: str = O365AuthMode.DIRECT,
        scopes: Optional[List[str]] = None,
        enable_sharepoint: bool = True,
        enable_onedrive: bool = True,
        **kwargs
    ):
        """
        Initialize complete file management toolkit.

        Args:
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_id: Azure AD tenant ID
            default_auth_mode: Default authentication mode
            scopes: Custom Graph API scopes
            enable_sharepoint: Enable SharePoint tools
            enable_onedrive: Enable OneDrive tools
            **kwargs: Additional arguments
        """
        self.logger = logging.getLogger('Parrot.Toolkits.O365FileManagement')

        self.enable_sharepoint = enable_sharepoint
        self.enable_onedrive = enable_onedrive

        # Store credentials
        self.credentials = {
            'client_id': client_id,
            'tenant_id': tenant_id
        }

        if client_secret:
            self.credentials['client_secret'] = client_secret

        # Initialize sub-toolkits
        self._tools: List[Any] = []

        if enable_sharepoint:
            sp_toolkit = SharePointToolkit(
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                default_auth_mode=default_auth_mode,
                scopes=scopes
            )
            self._tools.extend(sp_toolkit.get_tools())

        if enable_onedrive:
            od_toolkit = OneDriveToolkit(
                client_id=client_id,
                client_secret=client_secret,
                tenant_id=tenant_id,
                default_auth_mode=default_auth_mode,
                scopes=scopes
            )
            self._tools.extend(od_toolkit.get_tools())

        self.logger.info(
            f"Office365FileManagementToolkit initialized with {len(self._tools)} tools"
        )

    def get_tools(self) -> List[Any]:
        """Get all toolkit tools."""
        return self._tools

    def get_tool_by_name(self, name: str) -> Optional[Any]:
        """Get a specific tool by name."""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    def get_sharepoint_tools(self) -> List[Any]:
        """Get only SharePoint tools."""
        return [
            tool for tool in self._tools
            if isinstance(tool, (
                ListSharePointFilesTool,
                SearchSharePointFilesTool,
                DownloadSharePointFileTool,
                UploadSharePointFileTool
            ))
        ]

    def get_onedrive_tools(self) -> List[Any]:
        """Get only OneDrive tools."""
        return [
            tool for tool in self._tools
            if isinstance(tool, (
                ListOneDriveFilesTool,
                SearchOneDriveFilesTool,
                DownloadOneDriveFileTool,
                UploadOneDriveFileTool
            ))
        ]

    async def cleanup(self):
        """Clean up all tool resources."""
        for tool in self._tools:
            try:
                await tool.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up tool {tool.name}: {e}")

    def __repr__(self) -> str:
        tool_names = [tool.name for tool in self._tools]
        return f"Office365FileManagementToolkit(tools={tool_names})"


# ============================================================================
# Factory Functions
# ============================================================================

def create_sharepoint_toolkit(
    client_id: str,
    client_secret: str,
    tenant_id: str,
    **kwargs
) -> SharePointToolkit:
    """
    Factory function to create a SharePoint toolkit.

    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        tenant_id: Azure AD tenant ID
        **kwargs: Additional toolkit arguments

    Returns:
        Configured SharePointToolkit instance
    """
    return SharePointToolkit(
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id,
        **kwargs
    )


def create_onedrive_toolkit(
    client_id: str,
    client_secret: str,
    tenant_id: str,
    **kwargs
) -> OneDriveToolkit:
    """
    Factory function to create a OneDrive toolkit.

    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        tenant_id: Azure AD tenant ID
        **kwargs: Additional toolkit arguments

    Returns:
        Configured OneDriveToolkit instance
    """
    return OneDriveToolkit(
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id,
        **kwargs
    )


def create_file_management_toolkit(
    client_id: str,
    client_secret: str,
    tenant_id: str,
    **kwargs
) -> Office365FileManagementToolkit:
    """
    Factory function to create a complete file management toolkit.

    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        tenant_id: Azure AD tenant ID
        **kwargs: Additional toolkit arguments

    Returns:
        Configured Office365FileManagementToolkit instance
    """
    return Office365FileManagementToolkit(
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id,
        **kwargs
    )


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    """
    Example usage of file management toolkits.
    """
    import asyncio
    from parrot.bots.agent import BasicAgent

    async def main():
        credentials = {
            'client_id': 'your-client-id',
            'client_secret': 'your-client-secret',
            'tenant_id': 'your-tenant-id'
        }

        # Example 1: SharePoint toolkit
        sp_toolkit = create_sharepoint_toolkit(**credentials)

        sp_agent = BasicAgent(
            name="SharePointAgent",
            role="SharePoint File Manager",
            tools=sp_toolkit.get_tools()
        )

        # Example 2: OneDrive toolkit
        od_toolkit = create_onedrive_toolkit(**credentials)

        od_agent = BasicAgent(
            name="OneDriveAgent",
            role="OneDrive File Manager",
            tools=od_toolkit.get_tools()
        )

        # Example 3: Complete file management toolkit
        file_toolkit = create_file_management_toolkit(**credentials)

        file_agent = BasicAgent(
            name="FileAgent",
            role="Office365 File Manager",
            tools=file_toolkit.get_tools()
        )

        print(f"SharePoint tools: {len(sp_toolkit.get_tools())}")
        print(f"OneDrive tools: {len(od_toolkit.get_tools())}")
        print(f"Total file management tools: {len(file_toolkit.get_tools())}")

    asyncio.run(main())


__all__ = [
    'SharePointToolkit',
    'OneDriveToolkit',
    'Office365FileManagementToolkit',
    'create_sharepoint_toolkit',
    'create_onedrive_toolkit',
    'create_file_management_toolkit'
]
