import { act, render, screen } from '@testing-library/react';
import ApiDocsPage from './ApiDocsPage';

beforeEach(() => {
  window.SwaggerUIBundle = jest.fn();
});

afterEach(() => {
  jest.clearAllMocks();
  delete window.SwaggerUIBundle;
});

test('renders embedded api docs shell and raw spec link', async () => {
  await act(async () => {
    render(<ApiDocsPage />);
  });

  expect(await screen.findByText('API Docs')).toBeTruthy();
  expect(screen.getByText('Open Raw OpenAPI')).toBeTruthy();
  expect(window.SwaggerUIBundle).toHaveBeenCalled();
});
