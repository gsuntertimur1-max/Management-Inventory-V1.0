import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, ShieldCheck, User as UserIcon, KeyRound, Trash2, Power } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { toast } from 'sonner';
import { ROLE_COLORS, ROLE_LABELS, canonicalRole, roleLabel } from '../lib/permissions';

const ROLES = ['Administrator', 'Supervisor', 'Operator', 'QC', 'Viewer'];

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const Modal = ({ title, onClose, children, locked = false }) => createPortal(
  <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
    <div
      className="card-surface w-full max-w-md p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-5">
        <h2 className="font-display text-xl font-bold">{title}</h2>
        <button
          data-testid="modal-close-btn"
          onClick={onClose}
          disabled={locked}
          className="text-[#8b93a1] hover:text-white disabled:opacity-50"
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </div>
  </div>,
  document.body
);

const Pengguna = () => {
  const { user, users, addUser, deleteUser, updateUser, changeUserPassword, canManageUsers } = useData();
  const isAdmin = canManageUsers;
  const [modal, setModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: '', username: '', email: '', role: 'Operator', password: '' });
  const [pwdModal, setPwdModal] = useState(null);
  const [newPwd, setNewPwd] = useState('');
  const [delModal, setDelModal] = useState(null);

  const save = async () => {
    if (!form.name.trim() || !form.username.trim() || !form.password) {
      toast.error('Nama, username & password wajib diisi');
      return;
    }
    if (saving) return;

    setSaving(true);
    try {
      await addUser({ ...form, name: form.name.trim(), username: form.username.trim() });
      toast.success('Pengguna ditambahkan');
      setModal(false);
      setForm({ name: '', username: '', email: '', role: 'Operator', password: '' });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const savePwd = async () => {
    if (newPwd.length < 6) { toast.error('Password minimal 6 karakter'); return; }
    try {
      await changeUserPassword(pwdModal.id, newPwd);
      toast.success(`Password ${pwdModal.name} diganti`);
      setPwdModal(null); setNewPwd('');
    } catch (e) { toast.error(apiError(e)); }
  };

  const confirmDelete = async () => {
    try {
      await deleteUser(delModal.id);
      toast.success(`Pengguna ${delModal.name} dihapus`);
      setDelModal(null);
    } catch (e) { toast.error(apiError(e)); }
  };

  const toggleActive = async (u) => {
    try {
      await updateUser(u.id, { active: !u.active });
      toast.success(u.active ? `${u.name} dinonaktifkan` : `${u.name} diaktifkan`);
    } catch (e) { toast.error(apiError(e)); }
  };

  const changeRole = async (u, role) => {
    try {
      await updateUser(u.id, { role });
      toast.success(`Peran ${u.name} diubah menjadi ${roleLabel(role)}`);
    } catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div className="space-y-6" data-testid="pengguna-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Kontrol Akses</div>
          <h1 className="font-display text-4xl font-bold">Pengguna</h1>
          <p className="text-[#8b93a1] mt-2">{users.length} akun terdaftar · {isAdmin ? 'kelola akun, peran & password' : 'hanya Superadmin yang dapat mengelola akun'}</p>
        </div>
        {isAdmin && (
          <button data-testid="add-user-btn" onClick={() => setModal(true)} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Tambah Pengguna</button>
        )}
      </div>

      <div className="card-surface p-4 text-xs text-[#aab4c4]">
        <span className="font-semibold text-white">Aturan akses:</span> Superadmin semua proses · Admin inbound, mutasi & outbound · Operator rebagging saja · QC QC saja · Viewer hanya dashboard, stok, inventory & riwayat transaksi.
      </div>

      <div className="card-surface p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Nama', 'Username', 'Email', 'Peran', 'Status', isAdmin ? 'Aksi' : ''].filter(Boolean).map((h) => <th key={h} className="py-2.5 pr-4 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} data-testid={`user-row-${u.username}`} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4"><div className="flex items-center gap-3"><div className="w-9 h-9 rounded-full bg-[#1a222e] flex items-center justify-center text-[#60a5fa]"><UserIcon size={16} /></div><span className="font-medium">{u.name}{u.id === user?.id && <span className="text-[10px] text-[#60a5fa] ml-2">(Anda)</span>}</span></div></td>
                  <td className="py-3 pr-4 font-mono text-xs text-[#8b93a1]">{u.username}</td>
                  <td className="py-3 pr-4 text-[#aab4c4]">{u.email || '—'}</td>
                  <td className="py-3 pr-4">
                    {isAdmin && u.id !== user?.id ? (
                      <select data-testid={`role-select-${u.username}`} value={canonicalRole(u.role)} onChange={(e) => changeRole(u, e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-1.5 text-xs outline-none focus:border-[#2563eb]" style={{ color: ROLE_COLORS[canonicalRole(u.role)] || '#8b93a1' }}>
                        {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                      </select>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium" style={{ background: `${ROLE_COLORS[canonicalRole(u.role)] || '#8b93a1'}22`, color: ROLE_COLORS[canonicalRole(u.role)] || '#8b93a1' }}><ShieldCheck size={12} /> {roleLabel(u.role)}</span>
                    )}
                  </td>
                  <td className="py-3 pr-4"><span className={`text-xs px-2.5 py-1 rounded-full ${u.active ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#6b7688]/15 text-[#8b93a1]'}`}>{u.active ? 'Aktif' : 'Nonaktif'}</span></td>
                  {isAdmin && (
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-1.5">
                        <button data-testid={`change-pwd-btn-${u.username}`} title="Ganti password" onClick={() => { setPwdModal(u); setNewPwd(''); }} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#eab308] hover:bg-[#eab308]/10"><KeyRound size={14} /></button>
                        {u.id !== user?.id && (
                          <>
                            <button data-testid={`toggle-active-btn-${u.username}`} title={u.active ? 'Nonaktifkan' : 'Aktifkan'} onClick={() => toggleActive(u)} className={`w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center ${u.active ? 'text-[#8b93a1]' : 'text-[#22c55e]'} hover:bg-[#141a24]`}><Power size={14} /></button>
                            <button data-testid={`delete-user-btn-${u.username}`} title="Hapus pengguna" onClick={() => setDelModal(u)} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] hover:bg-[#ef4444]/10"><Trash2 size={14} /></button>
                          </>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <Modal title="Tambah Pengguna" onClose={() => setModal(false)} locked={saving}>
          <div className="space-y-4">
            {[['name', 'Nama Lengkap'], ['username', 'Username'], ['email', 'Email (opsional)']].map(([k, l]) => (
              <div key={k}><label className="text-xs font-medium mb-1 block text-[#8b93a1]">{l}</label><input data-testid={`user-form-${k}`} value={form[k]} onChange={(e) => setForm((prev) => ({ ...prev, [k]: e.target.value }))} className={inputCls} /></div>
            ))}
            <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Password (min. 6 karakter)</label><input data-testid="user-form-password" type="password" value={form.password} onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))} className={inputCls} /></div>
            <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Peran</label><select data-testid="user-form-role" value={form.role} onChange={(e) => setForm((prev) => ({ ...prev, role: e.target.value }))} className={inputCls}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}</select></div>
          </div>
          <div className="flex justify-end gap-2 mt-6">
            <button onClick={() => setModal(false)} disabled={saving} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24] disabled:opacity-50">Batal</button>
            <button data-testid="user-form-submit" onClick={save} disabled={saving} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-60 disabled:cursor-wait">{saving ? 'Menyimpan…' : 'Simpan'}</button>
          </div>
        </Modal>
      )}

      {pwdModal && (
        <Modal title={`Ganti Password — ${pwdModal.name}`} onClose={() => setPwdModal(null)}>
          <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Password Baru (min. 6 karakter)</label><input data-testid="new-password-input" type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} className={inputCls} autoFocus /></div>
          <div className="flex justify-end gap-2 mt-6">
            <button onClick={() => setPwdModal(null)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button>
            <button data-testid="save-password-btn" onClick={savePwd} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold">Ganti Password</button>
          </div>
        </Modal>
      )}

      {delModal && (
        <Modal title="Hapus Pengguna" onClose={() => setDelModal(null)}>
          <p className="text-sm text-[#aab4c4]">Yakin ingin menghapus akun <span className="font-semibold text-white">{delModal.name}</span> (<span className="font-mono text-xs">{delModal.username}</span>)? Tindakan ini tidak dapat dibatalkan.</p>
          <div className="flex justify-end gap-2 mt-6">
            <button onClick={() => setDelModal(null)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button>
            <button data-testid="confirm-delete-user-btn" onClick={confirmDelete} className="px-5 py-2.5 rounded-lg text-sm font-semibold bg-[#ef4444] hover:bg-[#dc2626] text-white">Hapus</button>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default Pengguna;
