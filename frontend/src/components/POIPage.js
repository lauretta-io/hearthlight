import React, { useState, useEffect } from 'react';
import { BaseURL } from '../config';
import POICard from './POICard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import ImageUpload from './ImageUpload';
import '../styles/POIPage.css';

const POIPage = () => {
  const [POIname, setPOIname] = useState(() => {
    return localStorage.getItem('POIname') || '';
  });

  const [imageData, setImageData] = useState(() => {
    return {
      base64Strings: JSON.parse(localStorage.getItem('POIbase64Strings') || '[]'),
      fullImages: JSON.parse(localStorage.getItem('selectedPOIImages') || '[]')
    };
  });

  const [results, setResults] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitMessage, setSubmitMessage] = useState('');

  useEffect(() => {
    localStorage.setItem('POIname', POIname);
  }, [POIname]);

  useEffect(() => {
    localStorage.setItem('selectedPOIImages', JSON.stringify(imageData.fullImages));
    localStorage.setItem('POIbase64Strings', JSON.stringify(imageData.base64Strings));
  }, [imageData]);

  useEffect(() => {
    let isMounted = true;

    const fetchResults = async () => {
      try {
        const response = await fetch(`${BaseURL}/genetec/pois`);
        if (!response.ok) {
          throw new Error('Failed to fetch alerts; is the backend running?');
        }
        const data = await response.json();
        if (isMounted) {
          setResults(data);
        }
      } catch (error) {
        if (isMounted) {
          setError(error.message);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    fetchResults();
    const intervalId = setInterval(fetchResults, 5000);
    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, []);

  const handlePOInameChange = (event) => {
    setPOIname(event.target.value);
  };

  const clearImages = () => {
    setImageData({ base64Strings: [], fullImages: [] });
    setPOIname('');
    setSubmitMessage('');
    localStorage.removeItem('selectedPOIImages');
    localStorage.removeItem('POIbase64Strings');
    localStorage.removeItem('POIname');
  };

  const handleRegisterPOI = async () => {
    if (!POIname || imageData.base64Strings.length === 0) {
      setSubmitMessage('Provide a search name and at least one image.');
      return;
    }

    const payload = {
      "name": POIname,
      "images": imageData.base64Strings
    };

    try {
      const response = await fetch(`${BaseURL}/register_poi`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error('Failed to submit POI search');
      }

      clearImages();
      setSubmitMessage('POI search submitted. Results will appear below once processing completes.');
    } catch (error) {
      console.error('Error:', error);
      setSubmitMessage('Failed to submit POI search.');
    }
  };

  if (error) return <ErrorAlert message={error} />;
  if (isLoading) return <LoadingAlert message="Loading POI Searches..." />;

  return (
    <div className="poi-page">
      <section className="poi-page__hero">
        <div>
          <p className="poi-page__eyebrow">Person of Interest</p>
          <h1>Search by reference image and review matches in a real results grid.</h1>
          <p className="poi-page__lede">
            Upload one or more reference images, submit the search, and monitor matching
            entities as results arrive from the latest run.
          </p>
        </div>
        <div className="poi-page__hero-stats">
          <div className="poi-page__stat">
            <span>Saved searches</span>
            <strong>{results.length}</strong>
          </div>
          <div className="poi-page__stat">
            <span>Queued images</span>
            <strong>{imageData.fullImages.length}</strong>
          </div>
        </div>
      </section>

      {submitMessage && <div className="poi-page__message">{submitMessage}</div>}

      <div className="poi-page__layout">
        <section className="poi-panel poi-panel--search">
          <div className="poi-panel__header">
            <h2>Search Input</h2>
            <p>Stage reference images and submit a new POI search request.</p>
          </div>

          <label className="poi-page__field">
            <span>Search name</span>
            <input
              type="text"
              value={POIname}
              onChange={handlePOInameChange}
              placeholder="North Hall suspect"
              className="poi-page__input"
            />
          </label>

          <ImageUpload
            selectedImages={imageData}
            onImagesSelected={setImageData}
            onProcessingChange={setIsProcessing}
            className="poi-upload"
          />

          {isProcessing && (
            <div className="poi-page__processing">
              Processing images...
            </div>
          )}

          <div className="poi-page__actions">
            <button
              onClick={handleRegisterPOI}
              className="poi-page__primary"
              disabled={isProcessing}
            >
              Search {imageData.fullImages.length > 0 ? `(${imageData.fullImages.length} images)` : ''}
            </button>
            <button onClick={clearImages} className="poi-page__secondary">
              Clear
            </button>
          </div>
        </section>

        <section className="poi-panel poi-panel--results">
          <div className="poi-panel__header poi-panel__header--row">
            <div>
              <h2>Registered POI Searches</h2>
              <p>Newest searches from the current run, refreshed every 5 seconds.</p>
            </div>
            <span className="poi-page__pill">{results.length} total</span>
          </div>

          {results.length === 0 ? (
            <div className="poi-page__empty">
              No POI searches are registered for the latest run yet.
            </div>
          ) : (
            <div className="poi-results-grid">
              {results.map((poi) => (
                <POICard key={poi.id} poiCard={poi} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default POIPage;
