import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const textExtensions = new Set(['.json', '.txt', '.md', '.py', '.yaml', '.yml', '.csv', '.log', '.js', '.jsx', '.ts', '.tsx']);
const imageExtensions = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg']);
const videoExtensions = new Set(['.mp4', '.webm', '.mov', '.m4v', '.ogg']);
const audioExtensions = new Set(['.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac']);

export default function FilePreviewPane({ selectedFile, apiBase, mediaBase, libraryMediaBase }) {
  const [textContent, setTextContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const extension = (selectedFile?.extension || '').toLowerCase();
  const isText = textExtensions.has(extension);
  const isImage = imageExtensions.has(extension);
  const isVideo = videoExtensions.has(extension);
  const isAudio = audioExtensions.has(extension);
  const mediaUrl = useMemo(() => {
    if (!selectedFile?.path) return '';
    const safePath = selectedFile.path.trim();
    if (!safePath) return '';
    const encoded = safePath.split('/').map(encodeURIComponent).join('/');
    const resolvedLibraryBase = libraryMediaBase || mediaBase.replace(/\/media$/, '/library-media');
    if (safePath.startsWith('library/')) {
      return `${resolvedLibraryBase}/${encoded.slice('library/'.length)}`;
    }
    return `${mediaBase}/${encoded}`;
  }, [libraryMediaBase, mediaBase, selectedFile]);

  useEffect(() => {
    setTextContent('');
    setError('');

    if (!selectedFile || selectedFile.is_dir) return;
    if (!isText) return;

    const fetchText = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${apiBase}/sessions/file?path=${encodeURIComponent(selectedFile.path)}`);
        const content = res.data?.content || '';

        if (extension === '.json') {
          try {
            const parsed = JSON.parse(content);
            setTextContent(JSON.stringify(parsed, null, 2));
          } catch {
            setTextContent(content);
          }
        } else {
          setTextContent(content);
        }
      } catch {
        setError('Could not load file content for preview.');
      } finally {
        setLoading(false);
      }
    };

    fetchText();
  }, [apiBase, extension, isText, selectedFile]);

  if (!selectedFile || selectedFile.is_dir) {
    return (
      <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Select a file from the explorer to preview it here.
      </div>
    );
  }

  if (isImage) {
    return (
      <div style={{ height: '100%', width: '100%', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <img
          src={mediaUrl}
          alt={selectedFile.name}
          style={{ maxWidth: '100%', maxHeight: '100%', display: 'block', margin: '0 auto', borderRadius: '8px', boxShadow: '0 4px 20px rgba(0,0,0,0.35)' }}
        />
      </div>
    );
  }

  if (isVideo) {
    return (
      <div style={{ height: '100%', width: '100%', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <video
          src={mediaUrl}
          controls
          style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: '8px' }}
        />
      </div>
    );
  }

  if (isAudio) {
    return (
      <div style={{ height: '100%', width: '100%', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
        <audio src={mediaUrl} controls style={{ width: '100%' }} />
      </div>
    );
  }

  if (isText) {
    if (loading) {
      return <div style={{ color: 'var(--text-muted)' }}>Loading text preview...</div>;
    }
    if (error) {
      return <div style={{ color: 'var(--danger)' }}>{error}</div>;
    }
    return (
      <div style={{ height: '100%', width: '100%', overflow: 'auto' }}>
        <pre style={{ background: 'transparent', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.85rem', lineHeight: '1.5', color: 'var(--text-main)', fontFamily: 'monospace' }}>
          {textContent}
        </pre>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', color: 'var(--text-muted)', height: '100%', width: '100%', overflow: 'auto' }}>
      <div>Preview is not available for this file type.</div>
      <a href={mediaUrl} target="_blank" rel="noreferrer" className="btn btn-primary" style={{ width: 'fit-content' }}>
        Open Raw File
      </a>
    </div>
  );
}
