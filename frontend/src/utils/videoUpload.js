const SUPPORTED_VIDEO_EXTENSIONS = ['mp4', 'mov', 'wmv', 'avi', 'avchd', 'flv', 'f4v', 'mkv', 'webm', 'ts'];
const VIDEO_UPLOAD_ACCEPT = SUPPORTED_VIDEO_EXTENSIONS.map((extension) => `.${extension}`).join(',');
const SUPPORTED_VIDEO_LABEL = SUPPORTED_VIDEO_EXTENSIONS.map((extension) => extension.toUpperCase()).join(', ');

const formatSupportedVideoExtensions = () =>
  SUPPORTED_VIDEO_EXTENSIONS.map((extension) => `.${extension}`).join(', ');

const getFileExtension = (filename) => {
  const segments = `${filename || ''}`.split('.');
  return segments.length > 1 ? segments.pop().toLowerCase() : '';
};

export const validateSelectedVideoFile = (file) => {
  if (!file) {
    return 'Choose a video file to upload.';
  }

  const extension = getFileExtension(file.name);
  if (!SUPPORTED_VIDEO_EXTENSIONS.includes(extension)) {
    return extension
      ? `Unsupported video type ".${extension}". Allowed: ${formatSupportedVideoExtensions()}`
      : `Uploaded files must include one of these extensions: ${formatSupportedVideoExtensions()}`;
  }

  if (file.type && file.type !== 'application/octet-stream' && !file.type.startsWith('video/')) {
    return `The selected file is not reported as a video by the browser. Allowed: ${formatSupportedVideoExtensions()}`;
  }

  return null;
};

export const formatUploadedVideoSummary = (upload) => {
  if (!upload) {
    return `Accepted formats: ${SUPPORTED_VIDEO_LABEL}`;
  }
  return `${upload.original_filename} (${Math.round(upload.size_bytes / 1024 / 1024)} MB)`;
};

export { SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_VIDEO_LABEL, VIDEO_UPLOAD_ACCEPT };
