"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@banking/api-client";
import { api } from "@/lib/api/client";

export function useWealthData() {
  const [products, setProducts] = useState<components["schemas"]["WealthProductResult"][]>([]);
  const [positions, setPositions] = useState<components["schemas"]["WealthPositionResult"][]>([]);
  const [orders, setOrders] = useState<components["schemas"]["WealthOrderResult"][]>([]);
  const [assessment, setAssessment] = useState<components["schemas"]["WealthAssessmentResult"] | null>(null);
  const [questionnaire, setQuestionnaire] = useState<Awaited<ReturnType<typeof api.wealthQuestionnaire>> | null>(null);
  const [accounts, setAccounts] = useState<components["schemas"]["AccountBalanceResult"][]>([]);
  const [workflows, setWorkflows] = useState<components["schemas"]["Workflow"][]>([]);
  const [feature, setFeature] = useState<components["schemas"]["WealthFeatureStatus"] | null>(null);
  const [refreshError, setRefreshError] = useState("");
  const inFlight = useRef<Promise<void> | null>(null);
  const staticKey = useRef("");
  const questionVersion = useRef("");
  const refresh = useCallback(async (force = true, reloadStatic = false) => {
    if (inFlight.current) {
      if (!force) return;
      await inFlight.current;
    }
    // A second forced caller may have started while the first caller awaited.
    if (inFlight.current) return inFlight.current;
    const run = async () => {
      const tasks = [api.wealthStatus(), api.wealthPositions(), api.wealthOrders(), api.wealthAssessment(), api.wealthAccounts(), api.wealthWorkflows()] as const;
      const [f,p,o,a,b,w] = await Promise.allSettled(tasks);
      let failed = [f,p,o,a,b,w].some(r => r.status === "rejected");
      if (f.status === "fulfilled") setFeature(f.value);
      if (p.status === "fulfilled") setPositions(p.value);
      if (o.status === "fulfilled") setOrders(o.value);
      if (a.status === "fulfilled") setAssessment(a.value);
      if (b.status === "fulfilled") setAccounts(b.value);
      if (w.status === "fulfilled") setWorkflows(w.value);
      const key = JSON.stringify([f.status === "fulfilled" ? f.value : null, a.status === "fulfilled" ? a.value : null]);
      const jobs: Promise<void>[] = [];
      if (reloadStatic || !staticKey.current || (f.status === "fulfilled" && a.status === "fulfilled" && key !== staticKey.current)) {
        jobs.push(api.wealthProducts().then(v => {setProducts(v); staticKey.current = key;}).catch(() => {failed = true;}));
      }
      const version = f.status === "fulfilled" ? f.value.questionnaire_version : "mock-v1";
      if (reloadStatic || questionVersion.current !== version) {
        jobs.push(api.wealthQuestionnaire().then(v => {setQuestionnaire(v); questionVersion.current = version;}).catch(() => {failed = true;}));
      }
      await Promise.all(jobs);
      setRefreshError(failed ? "刷新失败，已保留现有内容，正在重试" : "");
    };
    inFlight.current = run();
    try {await inFlight.current;} finally {inFlight.current = null;}
  }, []);
  useEffect(() => {
    const visible = () => document.visibilityState !== "hidden";
    const onVisible = () => {if (visible()) void refresh(false);};
    void refresh(false);
    const timer = setInterval(onVisible, 5000);
    document.addEventListener("visibilitychange", onVisible);
    return () => {clearInterval(timer); document.removeEventListener("visibilitychange", onVisible);};
  }, [refresh]);
  return {products, positions, orders, assessment, questionnaire, accounts, workflows, feature, refreshError, refresh};
}
