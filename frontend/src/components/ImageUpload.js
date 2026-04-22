import React from 'react';
import '../styles/ImageUpload.css';

const ImageUpload = ({
  selectedImages,
  onImagesSelected,
  onProcessingChange,
  className = '',
  allowMultiple = true,
  acceptedTypes = "image/*"
}) => {
  const handleDragOver = (event) => {
    event.preventDefault();
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const items = event.dataTransfer.items;
    handleItems(items);
  };

  const handleItems = async (items) => {
    onProcessingChange?.(true);
    const imageFiles = [];

    const processEntry = async (entry) => {
      if (entry.isFile) {
        return new Promise((resolve) => {
          entry.file(file => {
            if (file.type.startsWith('image/')) {
              imageFiles.push(file);
            }
            resolve();
          });
        });
      } else if (entry.isDirectory) {
        const dirReader = entry.createReader();
        return new Promise((resolve) => {
          dirReader.readEntries(async (entries) => {
            const promises = entries.map(entry => processEntry(entry));
            await Promise.all(promises);
            resolve();
          });
        });
      }
    };

    for (const item of items) {
      const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.();
      if (entry) {
        await processEntry(entry);
      } else if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file.type.startsWith('image/')) {
          imageFiles.push(file);
        }
      }
    }

    await Promise.all(imageFiles.map(file => encodeImageToBase64(file)));
    onProcessingChange?.(false);
  };

  const handleFileInput = async (event) => {
    const files = Array.from(event.target.files);
    onProcessingChange?.(true);
    await Promise.all(files.map(file => encodeImageToBase64(file)));
    onProcessingChange?.(false);
  };

  const handleDirectoryInput = async (event) => {
    const files = Array.from(event.target.files);
    onProcessingChange?.(true);
    await Promise.all(files.map(file => encodeImageToBase64(file)));
    onProcessingChange?.(false);
  };

  const encodeImageToBase64 = (file) => {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = reader.result.split(',')[1];
        const fullResult = reader.result;
        onImagesSelected?.(prev => ({
          base64Strings: [...(prev?.base64Strings || []), base64],
          fullImages: [...(prev?.fullImages || []), fullResult]
        }));
        resolve();
      };
      reader.readAsDataURL(file);
    });
  };

  const DefaultButtons = () => (
    <div className="upload-buttons">
      <input
        type="file"
        onChange={handleFileInput}
        multiple={allowMultiple}
        accept={acceptedTypes}
        id="file-input"
        className="file-input"
      />
      <input
        type="file"
        onChange={handleDirectoryInput}
        webkitdirectory="true"
        directory="true"
        id="directory-input"
        className="file-input"
      />
      <label htmlFor="file-input" className="file-input-label">
        Select Files
      </label>
      <label htmlFor="directory-input" className="file-input-label">
        Select Folder
      </label>
    </div>
  );

  const DefaultPreview = () => (
    <div className="selected-images">
      {selectedImages?.fullImages?.map((img, index) => (
        <img
          key={index}
          src={img}
          alt={`Selected ${index + 1}`}
          className="preview-image"
        />
      ))}
    </div>
  );

  return (
    <div
      className={`drag-drop-area ${className} ${selectedImages?.fullImages?.length > 0 ? 'has-images' : ''}`}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <DefaultButtons />
      <p className="drag-drop-text">Or drag and drop files/folder here</p>
      <DefaultPreview />
    </div>
  );
};

export default ImageUpload;
