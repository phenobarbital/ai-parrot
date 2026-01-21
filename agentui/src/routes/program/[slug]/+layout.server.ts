// src/routes/program/[slug]/+layout.server.ts

/**
 * Program Layout Server Load
 * Loads program data with modules and submodules
 */

import { error } from '@sveltejs/kit';
import { getProgramBySlug } from '$lib/data/mock-data';

export async function load({ params, locals }: { params: { slug: string }; locals: App.Locals }) {
    const { client } = locals;
    const { slug } = params;

    if (!client) {
        throw error(404, 'Client not found');
    }

    const program = getProgramBySlug(client, slug);

    if (!program) {
        throw error(404, 'Program not found');
    }

    return {
        client,
        program,
        modules: program.modules || []
    };
}
