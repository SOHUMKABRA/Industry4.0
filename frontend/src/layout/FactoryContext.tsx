import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Factory } from "../api/types";
import { useApi } from "../lib/useApi";

const KEY = "twin.factory";

interface FactoryState {
  factories: Factory[];
  factory: Factory | null;
  select: (id: string) => void;
  reload: () => Promise<void>;
  loading: boolean;
}

const Ctx = createContext<FactoryState | null>(null);

export function FactoryProvider({ children }: { children: ReactNode }) {
  const { data, loading, reload } = useApi(() => api.get<Factory[]>("/factories"), []);
  const [selected, setSelected] = useState<string | null>(() => {
    try { return localStorage.getItem(KEY); } catch { return null; }
  });
  const factories = data ?? [];
  const factory = factories.find((f) => f.id === selected) ?? factories[0] ?? null;

  useEffect(() => {
    if (factory) try { localStorage.setItem(KEY, factory.id); } catch { /* ignore */ }
  }, [factory]);

  const value = useMemo<FactoryState>(
    () => ({ factories, factory, select: setSelected, reload, loading }),
    [factories, factory, reload, loading],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFactory(): FactoryState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFactory outside FactoryProvider");
  return v;
}
