import { ReactNode, useEffect } from "react";
import { useFactory } from "../layout/FactoryContext";
import { liveClient } from "./LiveClient";

/** Keeps one WebSocket subscribed to the selected factory. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { factory } = useFactory();
  const fid = factory?.id;
  useEffect(() => {
    if (fid) liveClient.connect(fid);
  }, [fid]);
  useEffect(() => () => liveClient.close(), []);
  return <>{children}</>;
}
