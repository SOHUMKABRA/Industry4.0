// Small inline stroke-icon set (no icon library dependency).
const PATHS: Record<string, string> = {
  overview: "M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z",
  factory: "M2 20h20M4 20V10l5 3V10l5 3V10l5 3V4h2v16",
  assets: "M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10",
  devices: "M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3M5 5h14v14H5zM9 9h6v6H9z",
  types: "M4 6h16M4 12h10M4 18h7M17 15l2 2 3-4",
  audit: "M9 3h6l1 2h3v16H5V5h3zM9 11h6M9 15h4",
  editor: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 18l9 5 9-5",
  live: "M3 12h4l3-8 4 16 3-8h4",
  control: "M5 21V14M5 10V3M12 21v-9M12 8V3M19 21v-5M19 12V3M2 14h6M9 8h6M16 16h6",
  automation: "M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8",
  alert: "M12 3l10 18H2zM12 10v5M12 18v.01",
  sim: "M10 2v6L4 20h16L14 8V2M8 2h8M7 15h10",
  analytics: "M3 21h18M6 17V9M11 17V5M16 17v-6M21 17v-9",
  plus: "M12 5v14M5 12h14",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14zM21 21l-5-5",
  x: "M6 6l12 12M18 6L6 18",
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M21 13A9 9 0 1111 3a7 7 0 0010 10z",
  menu: "M4 6h16M4 12h16M4 18h16",
  logout: "M15 3h4v18h-4M10 17l5-5-5-5M15 12H3",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14",
  copy: "M8 8h12v12H8zM4 16V4h12",
  plug: "M9 2v6M15 2v6M6 8h12v4a6 6 0 01-12 0zM12 18v4",
  check: "M5 12l5 5 9-10",
  chevron: "M9 6l6 6-6 6",
  edit: "M4 20h4L20 8l-4-4L4 16zM14 6l4 4",
  refresh: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
  link: "M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1",
};

export function Icon({ name, size = 16, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={PATHS[name] ?? PATHS.assets} />
    </svg>
  );
}
