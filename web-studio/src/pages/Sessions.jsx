import { useState } from 'react';
import axios from 'axios';
import { Folder, FileText, Image as ImageIcon, Video, Download, RefreshCcw } from 'lucide-react';
import SessionTreeView from '../components/SessionTreeView';
import FilePreviewPane from '../components/FilePreviewPane';

const API_BASE = 'http://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';

export default function Sessions() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState('');
  const [treeRefreshToken, setTreeRefreshToken] = useState(0);

  const loadChildren = async (path = '') => {
    try {
      const res = await axios.get(`${API_BASE}/sessions/tree?path=${encodeURIComponent(path)}`);
      return res.data;
    } catch (err) {
      console.error(err);
      setError('Failed to load directory tree. Is the API running?');
      return [];
    }
  };

  const handleSelect = async (item) => {
    setSelectedFile(item);
    setError('');
  };

  const getMediaUrl = (path) => `${MEDIA_BASE}/${path.split('/').map(encodeURIComponent).join('/')}`;

  const renderIcon = (item) => {
    if (item.is_dir) return <Folder size={16} className="text-accent" />;
    const ext = item.extension;
    if (['.mp4', '.gif', '.mov'].includes(ext)) return <Video size={16} className="text-danger" />;
    if (['.png', '.jpg', '.jpeg'].includes(ext)) return <ImageIcon size={16} className="text-primary" />;
    return <FileText size={16} className="text-muted" />;
  };

  return (
    <div style={{ display: 'flex', height: '100%', gap: '1.5rem', flex: 1 }}>
      
      {/* LEFT PANE - TREE */}
      <div className="glass-panel" style={{ width: '320px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
          <h3 style={{ margin: 0, fontSize: '1rem' }}>Session Files</h3>
          <button
            className="btn"
            type="button"
            title="Refresh session files"
            onClick={() => setTreeRefreshToken((prev) => prev + 1)}
            style={{ padding: '0.2rem 0.35rem' }}
          >
            <RefreshCcw size={14} />
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0.5rem' }}>
          {error && <div style={{ color: 'var(--danger)', marginBottom: '0.5rem' }}>{error}</div>}
          <SessionTreeView
            rootPath={''}
            loadChildren={loadChildren}
            onItemSelect={handleSelect}
            selectedPath={selectedFile?.path || ''}
            refreshToken={treeRefreshToken}
          />
        </div>
      </div>

      {/* RIGHT PANE - PREVIEW */}
      <div className="glass-panel animate-fade-in" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
         <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                {selectedFile ? renderIcon(selectedFile) : <FileText size={16} />}
                {selectedFile ? selectedFile.name : 'No file selected'}
              </h3>
              {selectedFile?.size && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{(selectedFile.size / 1024).toFixed(1)} KB</span>}
            </div>
            
            {selectedFile && !selectedFile.is_dir && (
              <a href={getMediaUrl(selectedFile.path)} target="_blank" rel="noreferrer" className="btn btn-primary">
                <Download size={16} /> Open Raw
              </a>
            )}
         </div>
         
         <div style={{ flex: 1, overflow: 'auto', padding: '1.5rem', background: 'var(--bg-base)' }}>
            <FilePreviewPane
              selectedFile={selectedFile}
              apiBase={API_BASE}
              mediaBase={MEDIA_BASE}
            />
         </div>
      </div>
    </div>
  );
}
