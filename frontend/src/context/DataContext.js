import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import api, { setToken, apiError } from '../lib/api';
import { hasPermission, roleDestination, roleLabel } from '../lib/permissions';
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
  monitoringStock: [],
  consignmentDashboard: null,
  supplierReturns: [],
  settings: DEFAULT_SETTINGS,
};

export const DataProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [state, setState] = useState(EMPTY);
  const [theme, setThemeState] = useState(() => localStorage.getItem('bulog_theme') || 'dark');
  const [consignmentLastSync, setConsignmentLastSync] = useState(null);
  const [consignmentSyncing, setConsignmentSyncing] = useState(false);
  const consignmentSyncInFlight = useRef(false);

  const setTheme = useCallback((nextTheme) => {
    setThemeState(nextTheme === 'light' ? 'light' : 'dark');
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('bulog_theme', theme);
  }, [theme]);

  const fetchAll = useCallback(async () => {
    try {
      const scopedDestination = roleDestination(user?.role);
      if (scopedDestination) {
        const [p, consignmentStockRes, consignmentLayoutsRes, consignmentHistoryRes, consignmentOpnamesRes, monitoringStockRes, consignmentDashboardRes, settingsRes] = await Promise.all([
          api.get('/product-catalog'),
          api.get('/consignment-stock'),
          api.get('/consignment-layouts'),
          api.get('/consignment-layout-history'),
          api.get('/consignment-opnames'),
          api.get('/monitoring-stock'),
          api.get('/dashboard-consignment-position'),
          api.get('/settings'),
        ]);
        setState({
          ...EMPTY,
          products: p.data,
          consignmentStock: consignmentStockRes.data,
          consignmentLayouts: consignmentLayoutsRes.data,
          consignmentLayoutHistory: consignmentHistoryRes.data,
          consignmentOpnames: consignmentOpnamesRes.data,
          monitoringStock: monitoringStockRes.data,
          consignmentDashboard: consignmentDashboardRes.data,
          settings: { ...DEFAULT_SETTINGS, ...settingsRes.data },
        });
        return;
      }
      const [p, suppliersRes, sj, loads, po, t, stacks, treatments, consignmentStockRes, consignmentLayoutsRes, consignmentHistoryRes, consignmentOpnamesRes, monitoringStockRes, consignmentDashboardRes, supplierReturnsRes, settingsRes, usersRes] = await Promise.all([
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
        api.get('/monitoring-stock'),
        api.get('/dashboard-consignment-position'),
        api.get('/supplier-returns'),
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
        monitoringStock: monitoringStockRes.data,
        consignmentDashboard: consignmentDashboardRes.data,
        supplierReturns: supplierReturnsRes.data,
        settings: { ...DEFAULT_SETTINGS, ...settingsRes.data },
      });
    } catch (e) {
      console.error('fetchAll failed', e);
    }
  }, [user?.role]);

  const refreshProducts = useCallback(async () => {
    const [productsRes, monitoringRes] = await Promise.all([
      api.get('/products'),
      api.get('/monitoring-stock'),
    ]);
    setState((prev) => ({ ...prev, products: productsRes.data, monitoringStock: monitoringRes.data }));
  }, []);

  const refreshInventoryFlow = useCallback(async () => {
    const [productsRes, transactionsRes, poRes, stacksRes, monitoringRes, supplierReturnsRes] = await Promise.all([
      api.get('/products'),
      api.get('/transactions'),
      api.get('/purchase-orders-v2'),
      api.get('/stack-allocations'),
      api.get('/monitoring-stock'),
      api.get('/supplier-returns'),
    ]);
    setState((prev) => ({
      ...prev,
      products: productsRes.data,
      transactions: transactionsRes.data,
      purchaseOrders: poRes.data,
      stackAllocations: stacksRes.data,
      monitoringStock: monitoringRes.data,
      supplierReturns: supplierReturnsRes.data,
    }));
  }, []);

  const refreshOutboundFlow = useCallback(async () => {
    const [loadsRes, sjRes, productsRes, transactionsRes, stacksRes, consignmentRes, monitoringRes] = await Promise.all([
      api.get('/outbound-loads'),
      api.get('/surat-jalan'),
      api.get('/products'),
      api.get('/transactions'),
      api.get('/stack-allocations'),
      api.get('/consignment-stock'),
      api.get('/monitoring-stock'),
    ]);
    setState((prev) => ({
      ...prev,
      outboundLoads: loadsRes.data,
      suratJalan: sjRes.data,
      products: productsRes.data,
      transactions: transactionsRes.data,
      stackAllocations: stacksRes.data,
      consignmentStock: consignmentRes.data,
      monitoringStock: monitoringRes.data,
    }));
  }, []);

  const refreshOutboundLoads = useCallback(async () => {
    const { data } = await api.get('/outbound-loads');
    setState((prev) => ({ ...prev, outboundLoads: data }));
    return data;
  }, []);

  const refreshPurchaseOrders = useCallback(async () => {
    const { data } = await api.get('/purchase-orders-v2');
    setState((prev) => ({ ...prev, purchaseOrders: data }));
  }, []);

  const refreshSuratJalan = useCallback(async () => {
    const { data } = await api.get('/surat-jalan');
    setState((prev) => ({ ...prev, suratJalan: data }));
  }, []);

  const refreshStacks = useCallback(async () => {
    const { data } = await api.get('/stack-allocations');
    setState((prev) => ({ ...prev, stackAllocations: data }));
  }, []);

  const refreshTreatments = useCallback(async () => {
    const { data } = await api.get('/stack-treatments');
    setState((prev) => ({ ...prev, stackTreatments: data }));
  }, []);

  const refreshConsignmentFlow = useCallback(async () => {
    if (consignmentSyncInFlight.current) return null;
    consignmentSyncInFlight.current = true;
    setConsignmentSyncing(true);
    try {
      const [stockRes, monitoringRes, dashboardRes] = await Promise.all([
        api.get('/consignment-stock'),
        api.get('/monitoring-stock'),
        api.get('/dashboard-consignment-position'),
      ]);
      setState((prev) => ({
        ...prev,
        consignmentStock: stockRes.data,
        monitoringStock: monitoringRes.data,
        consignmentDashboard: dashboardRes.data,
      }));
      setConsignmentLastSync(new Date());
      return stockRes.data;
    } finally {
      consignmentSyncInFlight.current = false;
      setConsignmentSyncing(false);
    }
  }, []);

  const refreshConsignmentLayouts = useCallback(async () => {
    const [layoutsRes, historyRes] = await Promise.all([
      api.get('/consignment-layouts'),
      api.get('/consignment-layout-history'),
    ]);
    setState((prev) => ({
      ...prev,
      consignmentLayouts: layoutsRes.data,
      consignmentLayoutHistory: historyRes.data,
    }));
  }, []);

  const refreshConsignmentOpnames = useCallback(async () => {
    const { data } = await api.get('/consignment-opnames');
    setState((prev) => ({ ...prev, consignmentOpnames: data }));
  }, []);

  useEffect(() => {
    // Auth utama memakai cookie HttpOnly. Bearer lama tetap dibaca interceptor
    // selama masa transisi, tetapi tidak lagi menjadi syarat untuk memulihkan sesi.
    api.get('/auth/me')
      .then((r) => {
        setUser(r.data);
        setToken(null);
      })
      .catch(() => setToken(null))
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => { if (user) fetchAll(); }, [user, fetchAll]);

  useEffect(() => {
    if (!user || !hasPermission(user?.role, 'consignmentView')) return undefined;

    const CONSIGNMENT_AUTO_SYNC_INTERVAL = 15000;
    let timerId = null;

    const syncIfVisible = () => {
      if (document.visibilityState !== 'visible' || !navigator.onLine) return;
      refreshConsignmentFlow().catch((error) => {
        if (process.env.NODE_ENV !== 'production') console.debug('consignment auto-sync skipped', error);
      });
    };

    const startTimer = () => {
      if (timerId) window.clearInterval(timerId);
      timerId = window.setInterval(syncIfVisible, CONSIGNMENT_AUTO_SYNC_INTERVAL);
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        syncIfVisible();
        startTimer();
      } else if (timerId) {
        window.clearInterval(timerId);
        timerId = null;
      }
    };

    const handleOnline = () => {
      syncIfVisible();
      startTimer();
    };

    syncIfVisible();
    startTimer();
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('online', handleOnline);

    return () => {
      if (timerId) window.clearInterval(timerId);
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('online', handleOnline);
    };
  }, [user, refreshConsignmentFlow]);


  const login = async (username, password) => {
    try {
      const { data } = await api.post('/auth/login', { username, password });
      // Token baru disimpan hanya pada cookie HttpOnly dari server.
      setToken(null);
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

  const addProduct = async (p) => { await api.post('/products-master', p); await refreshProducts(); };
  const updateProduct = async (id, patch) => { await api.put(`/products-master/${id}`, patch); await refreshProducts(); };
  const deleteProduct = async (id) => { await api.delete(`/products-master/${id}`); await refreshProducts(); };
  const addTransaction = async (payload) => { await api.post('/transactions', payload); await refreshInventoryFlow(); };
  const addReceipt = async (payload) => { const { data } = await api.post('/receipts', payload); await refreshInventoryFlow(); return data; };
  const recordStockDamage = async (payload) => { const { data } = await api.post('/stock-damage-discoveries', payload); await refreshInventoryFlow(); return data; };
  const createSupplierReturn = async (payload) => { const { data } = await api.post('/supplier-returns', payload); await refreshInventoryFlow(); return data; };
  const receiveSupplierReplacement = async (id, payload) => { const { data } = await api.post(`/supplier-returns/${id}/replacement`, payload); await refreshInventoryFlow(); return data; };

  const createOutboundLoad = async (payload) => {
    const { data } = await api.post('/outbound-loads', payload);
    setState((prev) => ({ ...prev, outboundLoads: [data, ...prev.outboundLoads] }));
    return data;
  };

  const startOutboundLoad = async (id) => {
    const { data } = await api.post(`/outbound-loads/${id}/start`);
    setState((prev) => ({
      ...prev,
      outboundLoads: prev.outboundLoads.map((item) => item.id === id ? data : item),
    }));
    return data;
  };

  const completeOutboundLoad = async (id, payload = {}) => {
    const { data } = await api.post(`/outbound-loads/${id}/complete`, payload);
    await refreshOutboundFlow();
    return data;
  };
  const createConsignmentReturn = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/return`, payload); await refreshOutboundFlow(); return data; };
  const createSalesReturn = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/sales-return`, payload); await refreshOutboundFlow(); return data; };
  const settleOutboundDocument = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/settle`, payload); await refreshOutboundFlow(); return data; };
  const settleOutboundDocuments = async (payload) => { const { data } = await api.post('/outbound-settlements/so', payload); await refreshOutboundFlow(); return data; };

  const updateSJStatus = async (id, status) => { await api.put(`/surat-jalan/${id}/status`, { status }); await refreshSuratJalan(); };
  const cancelOutboundLoad = async (id, payload) => { const { data } = await api.post(`/outbound-loads/${id}/cancel`, payload); await refreshOutboundLoads(); return data; };
  const editOutboundLoad = async (id, payload) => { const { data } = await api.put(`/outbound-loads/${id}/edit`, payload); await refreshOutboundLoads(); return data; };
  const cancelPurchaseOrder = async (id, payload) => { const { data } = await api.post(`/purchase-orders-v2/${id}/cancel`, payload); await refreshPurchaseOrders(); return data; };

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
    const { data } = await api.post('/import/master-xlsx', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
    await fetchAll();
    return data;
  };
  const addStackAllocation = async (payload) => { await api.post('/stack-allocations', payload); await refreshStacks(); };
  const updateStackAllocation = async (id, payload) => { await api.put(`/stack-allocations/${id}`, payload); await refreshStacks(); };
  const deleteStackAllocation = async (id) => { await api.delete(`/stack-allocations/${id}`); await refreshStacks(); };
  const addStackTreatment = async (payload) => { await api.post('/stack-treatments', payload); await refreshTreatments(); };
  const saveConsignmentLayout = async (payload) => { const { data } = await api.put('/consignment-layouts', payload); await refreshConsignmentLayouts(); return data; };
  const deleteConsignmentLayout = async (id) => { await api.delete(`/consignment-layouts/${id}`); await refreshConsignmentLayouts(); };
  const addConsignmentOpname = async (payload) => { await api.post('/consignment-opnames', payload); await refreshConsignmentOpnames(); };

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
      theme, setTheme,
      consignmentLastSync, consignmentSyncing,
      login, logout, ...state, fetchAll,
      addProduct, updateProduct, deleteProduct, addTransaction, addReceipt, recordStockDamage, createSupplierReturn, receiveSupplierReplacement,
      createOutboundLoad, refreshOutboundLoads, startOutboundLoad, completeOutboundLoad, createConsignmentReturn, createSalesReturn, settleOutboundDocument, settleOutboundDocuments, updateSJStatus, cancelOutboundLoad, editOutboundLoad, cancelPurchaseOrder,
      addSupplier, addPO, addUser, updateUser, deleteUser, changeUserPassword, updateSettings, resetData, importCsv,
      addStackAllocation, updateStackAllocation, deleteStackAllocation,
      addStackTreatment,
      saveConsignmentLayout,
      deleteConsignmentLayout,
      addConsignmentOpname,
      refreshConsignmentFlow,
    }}>
      {children}
    </DataContext.Provider>
  );
};

export default DataContext;
