import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';

const normalize = (value) => String(value || '').toLocaleLowerCase('id-ID').trim();

const SearchableProductSelect = ({
  products = [],
  value = '',
  onChange,
  disabled = false,
  placeholder = 'Ketik nama / SKU produk...',
  getDescription,
  emptyText = 'Produk tidak ditemukan',
  maxResults = 60,
  className = '',
  dataTestId,
}) => {
  const rootRef = useRef(null);
  const selected = products.find((item) => item.id === value);
  const selectedLabel = selected ? `${selected.name || ''}${selected.sku ? ` · ${selected.sku}` : ''}` : '';
  const [query, setQuery] = useState(selectedLabel);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) setQuery(selectedLabel);
  }, [selectedLabel, open]);

  useEffect(() => {
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const filtered = useMemo(() => {
    const needle = normalize(query);
    const source = !needle || needle === normalize(selectedLabel)
      ? products
      : products.filter((item) => normalize([
          item.name,
          item.sku,
          item.category,
          item.channel,
          item.unit,
        ].filter(Boolean).join(' ')).includes(needle));
    return source.slice(0, maxResults);
  }, [products, query, selectedLabel, maxResults]);

  const choose = (item) => {
    onChange?.(item.id);
    setQuery(`${item.name || ''}${item.sku ? ` · ${item.sku}` : ''}`);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <div className={`flex items-center rounded-lg border border-[#242f3d] bg-[#0b0f17] focus-within:border-[#2563eb] ${disabled ? 'opacity-70' : ''}`}>
        <Search size={14} className="ml-3 shrink-0 text-[#6b7688]" />
        <input
          type="text"
          data-testid={dataTestId}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          disabled={disabled}
          value={query}
          placeholder={placeholder}
          onFocus={(event) => {
            if (disabled) return;
            setOpen(true);
            if (selectedLabel) event.currentTarget.select();
          }}
          onChange={(event) => {
            const nextQuery = event.target.value;
            setQuery(nextQuery);
            setOpen(true);
            if (value && nextQuery !== selectedLabel) onChange?.('');
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpen(false);
            if (event.key === 'Enter' && open && filtered.length) {
              event.preventDefault();
              choose(filtered[0]);
            }
          }}
          className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-sm outline-none placeholder:text-[#566173]"
        />
        {!disabled && value && (
          <button
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => { onChange?.(''); setQuery(''); setOpen(true); }}
            className="p-1 text-[#6b7688] hover:text-[#e7ebf2]"
            title="Kosongkan produk"
          >
            <X size={14} />
          </button>
        )}
        <button
          type="button"
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => !disabled && setOpen((current) => !current)}
          className="mr-2 p-1 text-[#6b7688] disabled:cursor-not-allowed"
          tabIndex={-1}
        >
          <ChevronDown size={15} />
        </button>
      </div>

      {open && !disabled && (
        <div className="absolute z-[80] mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-[#2b3545] bg-[#0d121b] p-1 shadow-2xl">
          {filtered.length ? filtered.map((item) => {
            const description = getDescription?.(item);
            return (
              <button
                key={item.id}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(item)}
                className={`w-full rounded-md px-3 py-2 text-left hover:bg-[#172033] ${item.id === value ? 'bg-[#12213a]' : ''}`}
              >
                <div className="text-sm font-medium text-[#e7ebf2]">{item.name}</div>
                <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px] text-[#7f8ba0]">
                  {item.sku && <span className="font-mono text-[#93c5fd]">{item.sku}</span>}
                  {description && <span>{description}</span>}
                </div>
              </button>
            );
          }) : (
            <div className="px-3 py-4 text-center text-xs text-[#6b7688]">{emptyText}</div>
          )}
          {products.length > maxResults && filtered.length === maxResults && (
            <div className="border-t border-[#1f2937] px-3 py-2 text-[10px] text-[#6b7688]">Ketik nama atau SKU untuk mempersempit hasil.</div>
          )}
        </div>
      )}
    </div>
  );
};

export default SearchableProductSelect;
