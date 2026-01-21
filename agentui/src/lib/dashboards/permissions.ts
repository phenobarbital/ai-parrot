
export async function checkPermission(type: 'dashboard' | 'widget', id: string): Promise<boolean> {
    // Placeholder for permission check logic.
    // In a real implementation, this would call an API or check user tokens.
    // For now, valid IDs or logic can be mocked.
    console.log(`Checking permission for ${type} ${id}`);

    // Allow everything for demo purposes.
    return true;
}
