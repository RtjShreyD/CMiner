import { useEffect, useState, useMemo } from 'react';
import Tree from 'rc-tree';
import 'rc-tree/assets/index.css';

function treeNodesFromEntries(entries) {
  return entries.map((item) => ({
    title: item.name,
    key: item.path || item.name,
    isLeaf: !item.is_dir,
    children: item.is_dir ? [] : null,
    data: item,
  }));
}

function updateTreeData(list, key, children) {
  return list.map((node) => {
    if (node.key === key) {
      return { ...node, children };
    }
    if (node.children) {
      return { ...node, children: updateTreeData(node.children, key, children) };
    }
    return node;
  });
}

export default function SessionTreeView({ rootPath = null, loadChildren, onItemSelect, selectedPath, refreshToken = 0, emptyMessage = 'No files yet.' }) {
  const [treeData, setTreeData] = useState([]);
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [loadedKeys, setLoadedKeys] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadPath = async (path, options = {}) => {
    const { silent = false } = options;
    setError('');
    if (!silent) {
      setLoading(true);
    }
    try {
      const entries = await loadChildren(path);
      const childrenNodes = treeNodesFromEntries(entries);
      if (!path || path === rootPath) {
        setTreeData(childrenNodes);
      } else {
        setTreeData((prev) => updateTreeData(prev, path, childrenNodes));
      }
      setLoadedKeys((prev) => new Set(prev).add(path));
    } catch {
      setError('Unable to load directory');
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    setTreeData([]);
    setExpandedKeys([]);
    setLoadedKeys(new Set());
    setError('');
    if (rootPath === null || rootPath === undefined) {
      setLoading(false);
      return;
    }

    if (rootPath === '') {
      loadPath('');
    } else {
      loadPath(rootPath);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootPath]);

  useEffect(() => {
    if (rootPath === null || rootPath === undefined || refreshToken === 0) {
      return;
    }

    const keys = [...loadedKeys];
    const reloadPaths = keys.length > 0 ? keys : [rootPath];

    Promise.all(reloadPaths.map((p) => loadPath(p, { silent: true })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const onExpand = (newExpandedKeys, info) => {
    setExpandedKeys(newExpandedKeys);
    const key = String(info.node.key);
    const isLeaf = Boolean(info.node.isLeaf);
    if (info.expanded && !isLeaf && !loadedKeys.has(key)) {
      loadPath(key);
    }
  };

  const onSelectHandler = (keys, info) => {
    if (!keys || keys.length === 0) return;
    const key = String(keys[0]);
    const node = info.node;
    const isLeaf = Boolean(node.isLeaf);
    const nodeData = node.data;

    if (!isLeaf) {
      setExpandedKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
      if (!loadedKeys.has(key)) {
        loadPath(key);
      }
      return;
    }
    if (onItemSelect && nodeData) {
      onItemSelect(nodeData);
    }
  };

  const selectedKeys = useMemo(() => (selectedPath ? [selectedPath] : []), [selectedPath]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {error && <div style={{ color: 'var(--danger)', marginBottom: '0.4rem' }}>{error}</div>}
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {loading && treeData.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', padding: '0.75rem' }}>Loading filesystem...</div>
        ) : treeData.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', padding: '0.75rem' }}>{emptyMessage}</div>
        ) : (
          <Tree
            treeData={treeData}
            expandedKeys={expandedKeys}
            onExpand={onExpand}
            selectedKeys={selectedKeys}
            onSelect={onSelectHandler}
            autoExpandParent={false}
          />
        )}
      </div>
    </div>
  );
}
