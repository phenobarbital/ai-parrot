export const ssr = false;

export function load({ params }) {
  return {
    agentId: params.agentId
  };
}
