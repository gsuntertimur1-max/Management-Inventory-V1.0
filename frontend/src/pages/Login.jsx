import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, LogIn } from 'lucide-react';
import { useData } from '../context/DataContext';
import { toast } from 'sonner';

const Login = () => {
  const { login } = useData();
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const res = await login(username, password);
    if (res.ok) { toast.success('Berhasil masuk'); navigate('/'); }
    else toast.error(res.error || 'Username atau password salah');
  };

  return (
    <div className="app-bg flex flex-col items-center justify-center min-h-screen px-4">
      <div className="flex flex-col items-center text-center mb-8">
        <div className="bg-white rounded-2xl px-5 py-3 shadow-xl mb-4">
          <img src="/bulog-sunter.png" alt="BULOG Sunter Timur I & II" className="w-[220px] max-w-[70vw] h-auto" />
        </div>
        <div className="font-display font-bold text-xl tracking-tight">Sistem Manajemen Inventory Gudang</div>
        <div className="label-mono mt-1">Gudang Sunter Timur I &amp; II</div>
      </div>

      <div className="card-surface w-full max-w-md p-8 fade-up">
        <h1 className="font-display text-2xl font-bold mb-1">Masuk ke Akun Anda</h1>
        <p className="text-sm text-[#8b93a1] mb-6">Gunakan akun yang diberikan administrator gudang.</p>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-1.5 block">Username</label>
            <input data-testid="login-username-input" value={username} onChange={(e) => setUsername(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3.5 py-2.5 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30 transition" placeholder="admin" />
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">Password</label>
            <div className="relative">
              <input data-testid="login-password-input" type={show ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3.5 py-2.5 pr-11 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30 transition" />
              <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#8b93a1] hover:text-white">{show ? <EyeOff size={17} /> : <Eye size={17} />}</button>
            </div>
            <p className="text-xs text-[#6b7688] mt-1.5">Password peka huruf besar/kecil. Ketuk ikon mata untuk memeriksa ketikan Anda.</p>
          </div>
          <button data-testid="login-submit-btn" type="submit" className="btn-primary w-full flex items-center justify-center gap-2 py-2.5 rounded-lg font-semibold text-sm"><LogIn size={16} /> Masuk</button>
        </form>

        <div className="mt-6 p-3 rounded-lg bg-[#0b0f17] border border-[#1a222e] text-xs text-[#8b93a1] leading-relaxed">
          Gunakan akun yang dibuat administrator. Password awal administrator ditentukan melalui konfigurasi server dan harus segera diganti setelah masuk pertama kali.
        </div>
      </div>
    </div>
  );
};

export default Login;
