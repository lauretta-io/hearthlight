import React, { useEffect, useRef, useState } from 'react';
import { BaseURL } from '../config';
import '../styles/ApiDocsPage.css';

const SWAGGER_CSS_ID = 'swagger-ui-css';
const SWAGGER_SCRIPT_ID = 'swagger-ui-script';
const SWAGGER_CSS_URL = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css';
const SWAGGER_SCRIPT_URL = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js';

const ensureStylesheet = () => {
  if (document.getElementById(SWAGGER_CSS_ID)) {
    return;
  }
  const link = document.createElement('link');
  link.id = SWAGGER_CSS_ID;
  link.rel = 'stylesheet';
  link.href = SWAGGER_CSS_URL;
  document.head.appendChild(link);
};

const loadSwaggerBundle = () => new Promise((resolve, reject) => {
  if (window.SwaggerUIBundle) {
    resolve(window.SwaggerUIBundle);
    return;
  }

  const existingScript = document.getElementById(SWAGGER_SCRIPT_ID);
  if (existingScript) {
    existingScript.addEventListener('load', () => resolve(window.SwaggerUIBundle), { once: true });
    existingScript.addEventListener('error', () => reject(new Error('Failed to load Swagger UI assets.')), { once: true });
    return;
  }

  const script = document.createElement('script');
  script.id = SWAGGER_SCRIPT_ID;
  script.src = SWAGGER_SCRIPT_URL;
  script.async = true;
  script.onload = () => resolve(window.SwaggerUIBundle);
  script.onerror = () => reject(new Error('Failed to load Swagger UI assets.'));
  document.body.appendChild(script);
});

const ApiDocsPage = () => {
  const swaggerRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const mountSwagger = async () => {
      try {
        ensureStylesheet();
        const SwaggerUIBundle = await loadSwaggerBundle();
        if (cancelled || !swaggerRef.current || !SwaggerUIBundle) {
          return;
        }
        SwaggerUIBundle({
          url: `${BaseURL}/openapi.json`,
          domNode: swaggerRef.current,
          deepLinking: true,
          docExpansion: 'list',
          displayRequestDuration: true,
          filter: true,
        });
      } catch (mountError) {
        if (!cancelled) {
          setError(mountError.message);
        }
      }
    };

    mountSwagger();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="api-docs-page">
      <div className="api-docs-shell">
        <div className="api-docs-header">
          <div>
            <h2>API Docs</h2>
            <p className="api-docs-subtitle">
              Swagger-style endpoint documentation rendered inside the application.
            </p>
          </div>
          <a className="api-docs-link" href={`${BaseURL}/openapi.json`} target="_blank" rel="noreferrer">
            Open Raw OpenAPI
          </a>
        </div>

        {error && (
          <div className="api-docs-error">
            {error} Open the raw specification link above if the embedded viewer is blocked.
          </div>
        )}

        <div className="api-docs-viewer" ref={swaggerRef} />
      </div>
    </section>
  );
};

export default ApiDocsPage;
