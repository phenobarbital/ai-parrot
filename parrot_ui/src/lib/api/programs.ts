/**
 * Programs API Client
 * Fetches user programs from the backend API
 */

import { config } from '$lib/config';
import type { Program, Module } from '$lib/types';
import { getProgramBySlug } from '$lib/data/manual-data';

interface ApiProgram {
    program_id: number;
    program_name: string;
    description: string | null;
    program_slug: string;
    image_url: string | null;
    // Add other fields if needed for future use
}

/**
 * Fetch programs for the current user
 */
export async function fetchUserPrograms(token: string): Promise<Program[]> {
    try {
        const response = await fetch(`${config.apiBaseUrl}/api/v1/programs_user`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            console.error('Failed to fetch programs:', response.statusText);
            return [];
        }

        const apiPrograms: ApiProgram[] = await response.json();
        return mapApiProgramsToDomain(apiPrograms);
    } catch (error) {
        console.error('Error fetching programs:', error);
        return [];
    }
}

/**
 * Maps API response format to domain Program objects
 */
function mapApiProgramsToDomain(apiPrograms: ApiProgram[]): Program[] {
    return apiPrograms.map((p) => {
        // Create base program from API data
        const program: Program = {
            id: `prog-${p.program_id}`,
            slug: p.program_slug,
            name: p.program_name,
            description: p.description || '',
            icon: p.image_url || 'mdi:application', // Use image_url if available, or default icon
            modules: [], // API doesn't seem to return modules yet, start empty
            enabled: true
        };

        return program;
    });
}
