import React from 'react';

const PaginationControls = ({ page, totalItems, pageSize = 10, onChange, label = 'data' }) => {
  const totalPages = Math.max(1, Math.ceil(Number(totalItems || 0) / pageSize));
  const current = Math.min(Math.max(Number(page || 1), 1), totalPages);
  if (totalItems <= pageSize) return null;

  const start = (current - 1) * pageSize + 1;
  const end = Math.min(current * pageSize, totalItems);
  const pageNumbers = [];
  const first = Math.max(1, Math.min(current - 2, totalPages - 4));
  const last = Math.min(totalPages, Math.max(current + 2, 5));
  for (let value = first; value <= last; value += 1) pageNumbers.push(value);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-4">
      <div className="text-xs text-[#8b93a1]">
        Menampilkan {start}-{end} dari {totalItems} {label}
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={current <= 1}
          onClick={() => onChange(current - 1)}
          className="px-3 py-2 rounded-lg border border-[#283548] text-xs disabled:opacity-35"
        >
          Sebelumnya
        </button>
        {pageNumbers.map((value) => (
          <button
            type="button"
            key={value}
            onClick={() => onChange(value)}
            className={`min-w-9 px-2.5 py-2 rounded-lg border text-xs font-mono ${value === current ? 'border-[#2563eb] bg-[#2563eb]/15 text-[#93c5fd]' : 'border-[#283548] text-[#9aa6b7]'}`}
          >
            {value}
          </button>
        ))}
        <button
          type="button"
          disabled={current >= totalPages}
          onClick={() => onChange(current + 1)}
          className="px-3 py-2 rounded-lg border border-[#283548] text-xs disabled:opacity-35"
        >
          Selanjutnya
        </button>
      </div>
    </div>
  );
};

export default PaginationControls;
