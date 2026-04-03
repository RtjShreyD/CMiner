import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';
const LIBRARY_MEDIA_BASE = 'http://localhost:8000/library-media';

function mediaUrl(path) {
  if (!path || typeof path !== 'string') return '';
  const trimmed = path.trim();
  if (!trimmed) return '';
  const encoded = trimmed.split('/').map(encodeURIComponent).join('/');
  if (trimmed.startsWith('library/')) {
    return `${LIBRARY_MEDIA_BASE}/${encoded.slice('library/'.length)}`;
  }
  return `${MEDIA_BASE}/${encoded}`;
}

export default function Styles() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const profilesRes = await axios.get(`${API_BASE}/styles/profiles`);
        const p = profilesRes.data || [];
        setProfiles(p);
        if (p.length > 0) setSelectedProfileId(p[0].id);
      } catch (e) {
        setError(`Failed to load styles: ${e.message}`);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedProfileId) || null,
    [profiles, selectedProfileId],
  );

  const previewableProfiles = useMemo(
    () => profiles.filter((profile) => Boolean(profile?.preview_assets?.thumbnail)),
    [profiles],
  );

  const filteredProfiles = useMemo(
    () => (categoryFilter === 'all'
      ? previewableProfiles
      : previewableProfiles.filter((profile) => profile.category === categoryFilter)),
    [categoryFilter, previewableProfiles],
  );

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', height: '100%' }}>
      <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
        <h2 style={{ margin: 0, color: 'var(--text-accent)' }}>Styles Library</h2>
        <p style={{ margin: '0.5rem 0 0', color: 'var(--text-muted)' }}>
          Select cloud, font, subtitle, or render styles independently and preview each one directly.
        </p>
      </div>

      {error && (
        <div className="glass-panel" style={{ padding: '0.85rem 1rem', color: 'var(--danger)' }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '1rem', minHeight: 0, flex: 1 }}>
        <section className="glass-panel" style={{ padding: '1rem', minHeight: 0, overflow: 'auto' }}>
          <h3 style={{ marginTop: 0 }}>Profiles</h3>
          <div className="config-control" style={{ marginBottom: '0.75rem' }}>
            <label>Category</label>
            <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="all">All</option>
              <option value="cloud">Cloud</option>
              <option value="font">Font</option>
              <option value="subtitle">Subtitle</option>
              <option value="render">Render</option>
            </select>
          </div>
          {loading ? (
            <div style={{ color: 'var(--text-muted)' }}>Loading profiles...</div>
          ) : filteredProfiles.length === 0 ? (
            <div style={{ color: 'var(--text-muted)' }}>No style profiles found yet.</div>
          ) : (
            filteredProfiles.map((profile) => (
              <article
                key={profile.id}
                onClick={() => setSelectedProfileId(profile.id)}
                style={{
                  cursor: 'pointer',
                  border: profile.id === selectedProfileId ? '1px solid var(--text-accent)' : '1px solid var(--border-color)',
                  borderRadius: 10,
                  padding: '0.75rem',
                  marginBottom: '0.65rem',
                  background: 'var(--bg-surface)',
                }}
              >
                <img
                  src={mediaUrl(profile.preview_assets.thumbnail)}
                  alt={profile.name}
                  style={{ width: '100%', height: 110, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border-color)', marginBottom: '0.5rem' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                  <strong>{profile.name}</strong>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{profile.category}</span>
                </div>
                <div style={{ marginTop: '0.4rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>id: {profile.id}</div>
                {Array.isArray(profile.tags) && profile.tags.length > 0 && (
                  <div style={{ marginTop: '0.45rem', color: 'var(--text-accent)', fontSize: '0.8rem', whiteSpace: 'normal', wordBreak: 'break-word' }}>{profile.tags.join(' • ')}</div>
                )}
              </article>
            ))
          )}
        </section>

        <section className="glass-panel" style={{ padding: '1rem', minHeight: 0, overflow: 'auto' }}>
          <h3 style={{ marginTop: 0 }}>Preview</h3>
          {!selectedProfile ? (
            <div style={{ color: 'var(--text-muted)' }}>Select a profile from the left to preview.</div>
          ) : (
            <>
              <div style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                {selectedProfile.name} ({selectedProfile.category})
              </div>

              <div
                style={{
                  background: 'linear-gradient(135deg, #2f4587, #5d7fd4)',
                  minHeight: 220,
                  borderRadius: 12,
                  border: '1px solid rgba(255,255,255,0.18)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  padding: '1rem',
                  textAlign: 'center',
                  fontFamily: selectedProfile.config_json?.family || 'Inter, sans-serif',
                }}
              >
                "The city breathed in neon silence."
              </div>

              {selectedProfile.preview_assets?.thumbnail && (
                <img
                  src={mediaUrl(selectedProfile.preview_assets.thumbnail)}
                  alt="style preview"
                  style={{ marginTop: '0.75rem', width: '100%', maxHeight: 260, objectFit: 'cover', borderRadius: 10, border: '1px solid var(--border-color)' }}
                />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
