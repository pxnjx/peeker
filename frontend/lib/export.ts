/**
 * CSV download helpers for the report buttons. No dependencies: each section
 * builds its own headers/rows and hands them to downloadCsv.
 */

/** One cell per RFC 4180: always quoted, quotes doubled inside. */
function cell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  // Formula injection: a leading =, +, -, @, tab or CR can execute when the CSV
  // is opened in a spreadsheet, so string cells get a leading apostrophe.
  const guarded = typeof value === "string" && /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return `"${guarded.replace(/"/g, '""')}"`;
}

/** Whole table as CRLF-delimited CSV text (header row included). */
export function toCsv(
  headers: string[],
  rows: (string | number | null | undefined)[][],
): string {
  return [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
}

/**
 * Trigger a browser download of the table. The UTF-8 BOM keeps accented
 * author and business names intact when the file is opened in Excel.
 */
export function downloadCsv(
  filename: string,
  headers: string[],
  rows: (string | number | null | undefined)[][],
): void {
  const blob = new Blob([`\uFEFF${toCsv(headers, rows)}`], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** peeker-businesses-2026-09-28.csv */
export function reportName(kind: string): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `peeker-${kind}-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.csv`;
}
