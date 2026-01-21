// src/routes/+layout.server.ts

/**
 * Root Layout Server Load
 * Passes client data from locals to page context
 */

export async function load({ locals }: { locals: App.Locals }) {
    const { client } = locals;

    return {
        client,
        programs: client?.programs.filter((p) => p.enabled !== false) ?? []
    };
}
