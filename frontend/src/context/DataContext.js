import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import api, { setToken, apiError } from '../lib/api';

const DataContext = createContext(null);
export const useData = () => useContext(DataContext);

const EMPTY = { products: [], suppliers: [], suratJalan: [], purchaseOrders: [], users: [], transactions: [] };

export const DataProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [state, setState] = useState(EMPTY);

  const fetchAll = useCallback(async () => {
    try {
      const [p, s, sj, po, t] = await Promise.all([
        api.get('/products'), api.get('/suppliers'), api.get('/surat-jalan'),
        api.get('/purchase-orders'), api.get('/transactions'),
      ]);
      const users = user?.role === 'Administrator' ? (await api.get('/users')).data : [];
      setState({ products: p.data, suppliers: s.data, suratJalan: sj.data, purchaseOrders: po.data, users, transactions: t.data });
    } catch (e) {
      console.error('fetchAll failed', e);
    }
  }, [user?.role]);

  useEffect(() => {
    const token = localStorage.getItem('bulog_token');
    if (!token) { setChecking(false); return; }
    api.get('/auth/me')
      .then((r) => setUser(r.data))
      .catch(() => setToken(null))
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => { if (user) fetchAll(); }, [user, fetchAll]);

  const login = async (username, password) => {
    try {
      const { data } = await api.post('/auth/login', { username, password });
      setToken(data.token);
      setUser(data.user);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: apiError(e) };
    }
  };

  const logout = () => {
    api.post('/auth/logout').catch(() => {});
    setToken(null);
    setUser(null);
    setState(EMPTY);
  };

  const addProduct = async (p) => { await api.post('/products', p); await fetchAll(); };
  const updateProduct = async (id, patch) => { await api.put(`/products/${id}`, patch); await fetchAll(); };
  const deleteProduct = async (id) => { await api.delete(`/products/${id}`); await fetchAll(); };
  const addTransaction = async (payload) => { await api.post('/transactions', payload); await fetchAll(); };
  const updateSJStatus = async (id, status) => { await api.put(`/surat-jalan/${id}/status`, { status }); await fetchAll(); };
  // Update only the affected slice after small CRUD operations. This avoids
  // refetching every dashboard dataset after adding a supplier/user.
  const addSupplier = async (sup) => {
    const { data } = await api.post('/suppliers', sup);
    setState((prev) => ({ ...prev, suppliers: [...prev.suppliers, data] }));
    return data;
  };
  const addPO = async (po) => { await api.post('/purchase-orders', po); await fetchAll(); };
  const addUser = async (u) => {
    const { data } = await api.post('/users', u);
    setState((prev) => ({ ...prev, users: [...prev.users, data] }));
    return data;
  };
  const updateUser = async (id, patch) => {
    const { data } = await api.put(`/users/${id}`, patch);
    setState((prev) => ({
      ...prev,
      users: prev.users.map((item) => item.id === id ? data : item),
    }));
    return data;
  };
  const deleteUser = async (id) => {
    await api.delete(`/users/${id}`);
    setState((prev) => ({ ...prev, users: prev.users.filter((item) => item.id !== id) }));
  };
  const changeUserPassword = async (id, password) => { await api.put(`/users/${id}/password`, { password }); };
  const resetData = async () => { await api.post('/admin/reset-data'); await fetchAll(); };
  const importCsv = async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    const { data } = await api.post('/import/csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
    await fetchAll();
    return data;
  };

  return (
    <DataContext.Provider value={{
      user, checking, canWrite: ['Administrator', 'Supervisor', 'Operator'].includes(user?.role),
      login, logout, ...state, fetchAll,
      addProduct, updateProduct, deleteProduct, addTransaction, updateSJStatus,
      addSupplier, addPO, addUser, updateUser, deleteUser, changeUserPassword, resetData, importCsv,
    }}>
      {children}
    </DataContext.Provider>
  );
};
