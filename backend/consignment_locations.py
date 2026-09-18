from __future__ import annotations

from fastapi import HTTPException

BAZAR = "Gudang Bazar"
ECOM = "Gudang E-commerce"

CONSIGNMENT_STACK_CODES = {
    BAZAR: tuple(f"18/A0{i}-BAZAR" for i in range(1, 5)),
    ECOM: tuple(f"18/B0{i}(1/2)-ECOM" for i in range(1, 5)),
}


def consignment_stack_codes(destination: str) -> tuple[str, ...]:
    return CONSIGNMENT_STACK_CODES.get(str(destination or "").strip(), ())


def _compact(value: str) -> str:
    return str(value or "").strip().upper().replace("½", "1/2").replace(" ", "")


def normalize_consignment_stack_code(destination: str, value: str) -> str:
    destination = str(destination or "").strip()
    allowed = consignment_stack_codes(destination)
    if not allowed:
        raise HTTPException(status_code=400, detail="Lokasi konsinyasi tidak valid")

    raw = _compact(value)
    if not raw:
        raise HTTPException(status_code=400, detail=f"Kode tumpukan wajib diisi, contoh {allowed[0]}")

    aliases: dict[str, str] = {}
    if destination == BAZAR:
        for index, canonical in enumerate(allowed, 1):
            suffix = f"A0{index}"
            for alias in (canonical, suffix, f"18/{suffix}", f"BZR/{suffix}"):
                aliases[_compact(alias)] = canonical
    else:
        for index, canonical in enumerate(allowed, 1):
            old_suffix = f"A0{index}"
            suffix = f"B0{index}"
            for alias in (
                canonical,
                suffix,
                f"18/{suffix}",
                f"18/{suffix}(1/2)",
                f"ECOM/{suffix}",
                old_suffix,
                f"ECOM/{old_suffix}",
            ):
                aliases[_compact(alias)] = canonical

    canonical = aliases.get(raw)
    if canonical:
        return canonical

    raise HTTPException(
        status_code=400,
        detail=f"Kode tumpukan {destination} tidak valid. Pilih salah satu: {', '.join(allowed)}",
    )
