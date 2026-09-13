import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import api, { setToken, apiError } from '../lib/api';
import { hasPermission, roleLabel } from '../lib/permissions';
import { DEFAULT_CATEGORIES } from '../mock';

const DataContext = createContext(null);
export const useData = () => useContext(DataContext);

const DEFAULT_SETTINGS = {
  warehouse: 'Gudang Sunter Timur I & II',
  address: 'Jl. Sunter Agung, Jakarta Utara',
  categories: DEFAULT_CATEGORIES,
  lowAlert: true,
  expAlert: true,
  autoQueue: true,
};

const EMPTY = {
  products: [],
  suppliers: [],
  suratJalan: [],
  outboundLoads: [],
  purchaseOrders: [],
  users: [],
  transactions: [],
  stackAllocations: [],
  stackTreatments: [],
  consignmentStock: [],
  consignmentLayouts: [],
  consignmentLayoutHistory: [],
  consignmentOpnames: [],
  settings: DEFAULT_SETTINGS,
};

export const DataProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [state, setState] = useState(EMPTY);

  const fetchAll = useCallback(async () => {
    try {
      const [p, suppliersRes, sj, loads, po, t, stacks, treatments, consignmentStockRes, consignmentLayoutsRes, consignmentHistoryRes, consignmentOpnamesRes, settingsRes, usersRes] = await Promise.all([
        api.get('/products'),
        api.get('/suppliers'),
        api.get('/surat-jalan'),
        api.get('/outbound-loads'),
        api.get('/purchase-orders-v2'),
        api.get('/transactions'),
        api.get('/stack-allocations'),
        api.get('/stack-treatments'),
        api.get('/consignment-stock'),
        api.get('/consignment-layouts'),
        api.get('/consignment-layout-history'),
        api.get('/consignment-opnames'),
        api.get('/settings'),
        hasPermission(user?.role, 'users') ? api.get('/users') : Promise.resolve({ data: [] }),
      ]);
      setState({
        products: p.data,
        suppliers: suppliersRes.data,
        suratJalan: sj.data,
        outboundLoads: loads.data,
        purchaseOrders: po.data,
        users: usersRes.data,
        transactions: t.data,
        stackAllocations: stacks.data,
        stackTreatments: treatments.data,
        consignmentStock: consignmentStockRes.data,
        consignmentLayouts: consignmentLayoutsRes.data,
        consignmentLayoutHistory: consignmentHistoryRes.data,
        consignmentOpnames: consignmentOpnamesRes.data,
        settings: { ...DEFAULT_SETTINGS, ...settingsRes.data },
      });
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

  const addProduct = async (p) => { await api.post('/products-master', p); await fetchAll(); };
  const updateProduct = async (id, patch) => { await api.put(`/products-master/${id}`, patch); await fetchAll(); };
  const deleteProduct = async (id) => { await api.delete(`/products-master/${id}`); await fetchAll(); };
  const addTransaction = async (payload) => { await api.post('/transactions', payload); await fetchAll(); };
  const addReceipt = async (payload) => { const { data } = await api.post('/receipts', payload); await fetchAll(); return data; };

  const createOutboundLoad = async (payload) => {
    const { data } = await api.post('/outbound-loads', payload);
    setState((prev) => ({ ...prev, outboundLoads: [data, ...prev.outboundLoads] }));
    return data;
  };

  const refreshOutboundLoads = useCallback(async () => {
    const { data } = await api.get('/outbound-loads');
    setState((prev) => ({ ...prev, outboundLoads: data }));
    return data;
  }, []);

  const startOutboundLoad = async (id) => {
    const { data } = await api.post(`/outbound-loads/${id}/start`);
    setState((prev) => ({
      ...prev,
      outboundLoads: prev.outboundLoads.map((item) => item.id === id ? data : item),
    }));
    return data;
  };

  const completeOutboundLoad = async (id) => {
    const { data } = await api.post(`/outbound-loads/${id}/complete`);
    await fetchAll();
    return data;
  };
  const createConsignmentReturn = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/return`, payload); await fetchAll(); return data; };
  const settleOutboundDocument = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/settle`, payload); await fetchAll(); return data; };

  const updateSJStatus = async (id, status) => { await api.put(`/surat-jalan/${id}/status`, { status }); await fetchAll(); };

  const addSupplier = async (sup) => {
    const { data } = await api.post('/suppliers', sup);
    setState((prev) => ({ ...prev, suppliers: [...prev.suppliers, data] }));
    return data;
  };

  const addPO = async (po) => {
    const { data } = await api.post('/purchase-orders-v2', po);
    setState((prev) => ({ ...prev, purchaseOrders: [data, ...prev.purchaseOrders] }));
    return data;
  };

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
  const updateSettings = async (payload) => {
    const { data } = await api.put('/settings', payload);
    setState((prev) => ({ ...prev, settings: { ...DEFAULT_SETTINGS, ...data } }));
    return data;
  };
  const resetData = async () => { await api.post('/admin/reset-data'); await fetchAll(); };
  const importCsv = async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    const { data } = await api.post('/import/master-csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
    await fetchAll();
    return data;
  };
  const addStackAllocation = async (payload) => { await api.post('/stack-allocations', payload); await fetchAll(); };
  const updateStackAllocation = async (id, payload) => { await api.put(`/stack-allocations/${id}`, payload); await fetchAll(); };
  const deleteStackAllocation = async (id) => { await api.delete(`/stack-allocations/${id}`); await fetchAll(); };
  const addStackTreatment = async (payload) => { await api.post('/stack-treatments', payload); await fetchAll(); };
  const saveConsignmentLayout = async (payload) => { await api.put('/consignment-layouts', payload); await fetchAll(); };
  const addConsignmentOpname = async (payload) => { await api.post('/consignment-opnames', payload); await fetchAll(); };

  return (
    <DataContext.Provider value={{
      user,
      checking,
      roleLabel: roleLabel(user?.role),
      canWrite: hasPermission(user?.role, 'currentWrite'),
      canManageMasterData: hasPermission(user?.role, 'masterWrite'),
      canInbound: hasPermission(user?.role, 'inbound'),
      canOutbound: hasPermission(user?.role, 'outbound'),
      canRebagging: hasPermission(user?.role, 'rebagging'),
      canQC: hasPermission(user?.role, 'qc'),
      canManageUsers: hasPermission(user?.role, 'users'),
      canManageSettings: hasPermission(user?.role, 'settings'),
      login, logout, ...state, fetchAll,
      addProduct, updateProduct, deleteProduct, addTransaction, addReceipt,
      createOutboundLoad, refreshOutboundLoads, startOutboundLoad, completeOutboundLoad, createConsignmentReturn, settleOutboundDocument, updateSJStatus,
      addSupplier, addPO, addUser, updateUser, deleteUser, changeUserPassword, updateSettings, resetData, importCsv,
      addStackAllocation, updateStackAllocation, deleteStackAllocation,
      addStackTreatment,
      saveConsignmentLayout,
      addConsignmentOpname,
    }}>
      {children}
    </DataContext.Provider>
  );
};
