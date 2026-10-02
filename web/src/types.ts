export type Mechanism = {object: string; locus: string; operation: string; output: string; signal: string; assumptions: string[]};
export type Direction = {
  id: string; title: string; question: string; innovation: string; impact: string; feasibility: string;
  mechanism: Mechanism; claims: {text: string; status: string; source_ids: string[]}[];
  comparisons: {source_id: string; shared_foundation: string; difference: string; next_opportunity: string}[];
  unknowns: string[]; next_step: string; needs_update?: boolean;
};
export type Source = {id: string; title: string; url: string | null; text: string; kind: string; locator: string};
export type Run = {id: string; status: string; calls: number; tokens: number; usage_estimated: boolean;
  step: number; reason: string; elapsed: number; budget: {max_calls: number; max_tokens: number; max_minutes: number}};
export type Project = {
  id: string; revision: number; title: string; question: string; constraints: string;
  sources: Source[]; directions: Direction[]; selections: Record<string, string>;
  memories: {id: string; statement: string; conditions: string; status: string}[];
  feedback: {text: string; kind: string}[]; runs: Run[];
};
export type Event = {seq: number; kind: string; payload: {summary: string}; created: number};
