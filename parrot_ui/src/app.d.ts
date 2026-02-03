// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces

import type { Client, Program } from '$lib/types';
import type { UserInfo } from '$lib/navauth/types';

declare global {
    namespace App {
        // interface Error {}

        interface Locals {
            client: Client | null;
            clientSlug: string;
            token?: string;
            user?: UserInfo;
        }

        interface PageData {
            client?: Client | null;
            programs?: Program[];
        }

        // interface PageState {}
        // interface Platform {}
    }
}

export { };
