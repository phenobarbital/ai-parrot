import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import App from './App.svelte';

test('renders shell placeholder', () => {
  const { getByText } = render(App);
  expect(getByText(/parrot/i)).toBeTruthy();
});
