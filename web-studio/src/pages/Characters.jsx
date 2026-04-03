import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';
const MEDIA_BASE = 'http://localhost:8000/media';
const LIBRARY_MEDIA_BASE = 'http://localhost:8000/library-media';

function mediaUrl(path) {
  const safe = sanitizeImagePath(path);
  if (!safe) return '';
  const normalized = safe.split('/').map(encodeURIComponent).join('/');
  if (safe.startsWith('library/')) {
    return `${LIBRARY_MEDIA_BASE}/${normalized.slice('library/'.length)}`;
  }
  return `${MEDIA_BASE}/${normalized}`;
}

function sanitizeImagePath(path) {
  if (typeof path !== 'string') return '';
  const trimmed = path.trim();
  return trimmed.length > 0 ? trimmed : '';
}

function packPreviewImage(pack) {
  const fromPack = sanitizeImagePath(pack?.preview_assets?.thumbnail);
  if (fromPack) return fromPack;

  const fromCharacter = (pack?.characters || [])
    .flatMap((ch) => ch?.anchor_images || [])
    .map(sanitizeImagePath)
    .find(Boolean);

  return fromCharacter || '';
}

export default function Characters() {
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedPackId, setSelectedPackId] = useState('');

  const [prompt, setPrompt] = useState('A stoic cyber detective with an obsidian trench coat and glowing circuit tattoos.');
  const [name, setName] = useState('Kaelen Prototype');
  const [style, setStyle] = useState('cinematic anime');
  const [saveAsPack, setSaveAsPack] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generatedPreview, setGeneratedPreview] = useState(null);
  const [recentGenerated, setRecentGenerated] = useState([]);
  const [modelPreset, setModelPreset] = useState('gemini-2.5-flash-image');
  const [aspectRatio, setAspectRatio] = useState('1:1');
  const styleSuggestions = ['cinematic anime', 'manga noir', 'neon cyberpunk', 'storybook painterly'];

  const loadRecentGenerated = async () => {
    try {
      const response = await axios.get(`${API_BASE}/characters/generated`);
      setRecentGenerated(response.data || []);
    } catch {
      setRecentGenerated([]);
    }
  };

  const loadPacks = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.get(`${API_BASE}/characters/packs`);
      const data = response.data || [];
      setPacks(data);
    } catch (e) {
      setError(`Failed to load character packs: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPacks();
    loadRecentGenerated();
  }, []);

  const selectedPack = useMemo(
    () => packs.find((pack) => pack.id === selectedPackId) || null,
    [packs, selectedPackId],
  );

  const previewablePacks = useMemo(
    () => packs.filter((pack) => Boolean(packPreviewImage(pack))),
    [packs],
  );

  useEffect(() => {
    if (!selectedPackId && previewablePacks.length > 0) {
      setSelectedPackId(previewablePacks[0].id);
      return;
    }

    if (selectedPackId && !previewablePacks.some((pack) => pack.id === selectedPackId)) {
      setSelectedPackId(previewablePacks[0]?.id || '');
    }
  }, [previewablePacks, selectedPackId]);

  const selectedPackImage = selectedPack ? packPreviewImage(selectedPack) : null;

  const generatePreview = async () => {
    setGenerating(true);
    setError('');
    try {
      const response = await axios.post(`${API_BASE}/characters/generate-preview`, {
        prompt,
        style,
        name,
        model_preset: modelPreset,
        aspect_ratio: aspectRatio,
        save_as_pack: saveAsPack,
      });
      setGeneratedPreview(response.data);
      await loadRecentGenerated();
      if (saveAsPack) {
        await loadPacks();
      }
    } catch (e) {
      setError(`Generation failed: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', height: '100%' }}>
      <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
        <h2 style={{ margin: 0, color: 'var(--text-accent)' }}>Character Library</h2>
        <p style={{ margin: '0.5rem 0 0', color: 'var(--text-muted)' }}>
          Generate with Gemini for character previews and manage reusable packs in one place.
        </p>
      </div>

      {error && (
        <div className="glass-panel" style={{ padding: '0.85rem 1rem', color: 'var(--danger)' }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '1rem', minHeight: 0, flex: 1 }}>
        <section className="glass-panel" style={{ padding: '1rem', minHeight: 0, overflow: 'auto' }}>
          <h3 style={{ marginTop: 0 }}>Generate Character (Gemini)</h3>

          <div className="config-control" style={{ marginBottom: '0.6rem' }}>
            <label>Character Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="config-control" style={{ marginBottom: '0.6rem' }}>
            <label>Style</label>
            <input value={style} onChange={(e) => setStyle(e.target.value)} />
          </div>

          <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', marginBottom: '0.6rem' }}>
            {styleSuggestions.map((s) => (
              <button key={s} className="btn" type="button" onClick={() => setStyle(s)}>
                {s}
              </button>
            ))}
          </div>

          <div className="config-grid" style={{ marginBottom: '0.6rem' }}>
            <div className="config-control">
              <label>Model Preset</label>
              <select value={modelPreset} onChange={(e) => setModelPreset(e.target.value)}>
                <option value="gemini-2.5-flash-image">Gemini 2.5 Flash Image</option>
                <option value="gemini-default">Gemini Default</option>
              </select>
            </div>
            <div className="config-control">
              <label>Aspect Ratio</label>
              <select value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)}>
                <option value="1:1">1:1</option>
                <option value="3:4">3:4</option>
                <option value="9:16">9:16</option>
                <option value="16:9">16:9</option>
              </select>
            </div>
          </div>

          <div className="config-control" style={{ marginBottom: '0.6rem' }}>
            <label>Prompt</label>
            <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} style={{ width: '100%', resize: 'vertical' }} />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.8rem' }}>
            <input type="checkbox" checked={saveAsPack} onChange={(e) => setSaveAsPack(e.target.checked)} />
            Save as reusable character pack
          </label>

          <button className="btn btn-primary" onClick={generatePreview} disabled={generating}>
            {generating ? 'Generating...' : 'Generate Preview'}
          </button>

          {generatedPreview && (
            <div style={{ marginTop: '0.75rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              {generatedPreview.fallback_used ? 'Generated placeholder preview (Gemini fallback used).' : 'Gemini preview generated successfully.'}
            </div>
          )}

          <h3 style={{ marginTop: '1.2rem' }}>Existing Packs</h3>
          {loading ? (
            <div style={{ color: 'var(--text-muted)' }}>Loading packs...</div>
          ) : previewablePacks.length === 0 ? (
            <div style={{ color: 'var(--text-muted)' }}>No preview-ready character packs found yet.</div>
          ) : (
            previewablePacks.map((pack) => (
              <article
                key={pack.id}
                onClick={() => setSelectedPackId(pack.id)}
                style={{
                  cursor: 'pointer',
                  border: pack.id === selectedPackId ? '1px solid var(--text-accent)' : '1px solid var(--border-color)',
                  borderRadius: 10,
                  padding: '0.75rem',
                  marginBottom: '0.65rem',
                  background: 'var(--bg-surface)',
                }}
              >
                <img
                  src={mediaUrl(packPreviewImage(pack))}
                  alt={pack.name}
                  style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border-color)', marginBottom: '0.55rem' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                  <strong>{pack.name}</strong>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{pack.source_agent || 'unknown'}</span>
                </div>
                <div style={{ marginTop: '0.4rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>id: {pack.id}</div>
                <div style={{ marginTop: '0.35rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  characters: {Array.isArray(pack.characters) ? pack.characters.length : 0}
                </div>
              </article>
            ))
          )}
        </section>

        <section className="glass-panel" style={{ padding: '1rem', minHeight: 0, overflow: 'auto' }}>
          <h3 style={{ marginTop: 0 }}>Preview</h3>

          {generatedPreview?.image_path ? (
            <>
              <div style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }}>Generated Preview</div>
              <img
                src={mediaUrl(generatedPreview.image_path)}
                alt="generated character"
                style={{ width: '100%', maxHeight: 420, objectFit: 'contain', borderRadius: 10, border: '1px solid var(--border-color)', background: '#0d1023' }}
              />
            </>
          ) : selectedPack && selectedPackImage ? (
            <>
              <div style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }}>{selectedPack.name}</div>
              <img
                src={mediaUrl(selectedPackImage)}
                alt={selectedPack.name}
                style={{ width: '100%', maxHeight: 420, objectFit: 'contain', borderRadius: 10, border: '1px solid var(--border-color)', background: '#0d1023' }}
              />
            </>
          ) : (
            <div style={{ color: 'var(--text-muted)' }}>
              Generate a preview or select a pack to view character visuals.
            </div>
          )}

          {selectedPack?.characters?.length > 0 && (
            <div style={{ marginTop: '0.85rem' }}>
              <h4 style={{ marginBottom: '0.5rem' }}>Pack Characters</h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0.6rem' }}>
                {selectedPack.characters.map((ch) => {
                  const image = (ch.anchor_images || []).map(sanitizeImagePath).find(Boolean);
                  if (!image) {
                    return null;
                  }
                  return (
                    <div key={ch.character_id} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: '0.5rem' }}>
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-main)', marginBottom: '0.35rem' }}>{ch.display_name}</div>
                      <img
                        src={mediaUrl(image)}
                        alt={ch.display_name}
                        style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 6 }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div style={{ marginTop: '1rem' }}>
            <h4 style={{ marginBottom: '0.5rem' }}>Recent Generated</h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: '0.5rem' }}>
              {recentGenerated.map((item) => (
                <button
                  key={item.path}
                  className="btn"
                  style={{ padding: '0.25rem' }}
                  onClick={() => setGeneratedPreview({ image_path: item.path, fallback_used: false })}
                >
                  <img
                    src={mediaUrl(item.path)}
                    alt={item.name}
                    style={{ width: '100%', height: 90, objectFit: 'cover', borderRadius: 6 }}
                  />
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
