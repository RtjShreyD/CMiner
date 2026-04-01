import { useEffect, useState } from 'react';
import axios from 'axios';
import { Folder, FileText, Image as ImageIcon, Video, ChevronRight, ChevronDown, Download } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';

export default function Sessions() {
  const [treeContext, setTreeContext] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [error, setError] = useState('');

  const fetchTree = async (path = '') => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.get(`${API_BASE}/sessions/tree?path=${encodeURIComponent(path)}`);
      setItems(res.data);
      setTreeContext(path);
    } catch (err) {
      console.error(err);
      setError('Failed to load directory tree. Is the API running?');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTree();
  }, []);

  const handleSelect = async (item) => {
    if (item.is_dir) {
      fetchTree(item.path);
      return;
    }
    
    setSelectedFile(item);
    setFileContent('');
    setError('');

    // If it's a text file, fetch its contents
    const textExts = ['.json', '.txt', '.md', '.py', '.yaml', '.csv', '.log'];
    if (textExts.includes(item.extension)) {
      try {
        const res = await axios.get(`${API_BASE}/sessions/file?path=${encodeURIComponent(item.path)}`);
        setFileContent(res.data.content);
      } catch (err) {
        setError('Could not load text content.');
      }
    }
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
        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: '1rem' }}>Explorer</h3>
          {treeContext && (
             <button onClick={() => fetchTree(treeContext.split('/').slice(0, -1).join('/'))} 
                     className="btn" style={{ marginLeft: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}>
                Back Up
             </button>
          )}
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: '0.5rem' }}>
          {loading ? (
             <div style={{ padding: '2rem', textAlign: 'center', opacity: 0.5 }}>Scanning workspace...</div>
          ) : error ? (
             <div style={{ padding: '1rem', color: 'var(--danger)' }}>{error}</div>
          ) : items.length === 0 ? (
             <div style={{ padding: '2rem', textAlign: 'center', opacity: 0.5 }}>Empty Directory</div>
          ) : (
             <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
               {items.map(item => (
                 <li 
                    key={item.path} 
                    onClick={() => handleSelect(item)}
                    style={{ 
                      padding: '8px 12px', 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: '10px',
                      cursor: 'pointer',
                      borderRadius: '6px',
                      background: selectedFile?.path === item.path ? 'var(--bg-surface-hover)' : 'transparent',
                      color: selectedFile?.path === item.path ? 'var(--primary)' : 'inherit',
                      transition: 'background 0.2s',
                    }}
                    onMouseEnter={(e) => { if(selectedFile?.path !== item.path) e.currentTarget.style.background = 'var(--bg-surface)' }}
                    onMouseLeave={(e) => { if(selectedFile?.path !== item.path) e.currentTarget.style.background = 'transparent' }}
                 >
                   {renderIcon(item)}
                   <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.9rem' }}>
                     {item.name}
                   </span>
                   {item.is_dir && <ChevronRight size={14} opacity={0.5} />}
                 </li>
               ))}
             </ul>
          )}
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
            {!selectedFile || selectedFile.is_dir ? (
              <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                Select a file from the explorer to preview it here.
              </div>
            ) : ['mp4', 'webm', 'mov'].includes(selectedFile.extension?.replace('.', '')) ? (
              <video 
                src={getMediaUrl(selectedFile.path)} 
                controls 
                autoPlay 
                style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: '8px' }} 
              />
            ) : ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(selectedFile.extension?.replace('.', '')) ? (
              <img 
                src={getMediaUrl(selectedFile.path)} 
                alt="preview" 
                style={{ maxWidth: '100%', maxHeight: '100%', display: 'block', margin: '0 auto', borderRadius: '8px', boxShadow: '0 4px 20px rgba(0,0,0,0.5)' }} 
              />
            ) : (
              <pre style={{ 
                background: 'transparent', 
                margin: 0, 
                whiteSpace: 'pre-wrap', 
                wordBreak: 'break-word',
                fontSize: '0.85rem',
                lineHeight: '1.5',
                color: 'var(--text-main)',
                fontFamily: 'monospace'
              }}>
                {fileContent || <span style={{color: 'var(--text-muted)'}}>Loading content...</span>}
              </pre>
            )}
         </div>
      </div>
    </div>
  );
}
