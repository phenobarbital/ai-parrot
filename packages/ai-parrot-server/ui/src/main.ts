import { mount } from 'svelte';
import './app.css';
// FEAT-476: register bundled @iconify-json/* collections before mount so
// every <Icon icon="prefix:name" /> in the AgentChat tree resolves
// offline (see src/lib/icons.ts).
import './lib/icons';
import App from './App.svelte';

const target = document.getElementById('app');

if (!target) {
  throw new Error('Admin UI root element (#app) not found in index.html');
}

const app = mount(App, { target });

export default app;
