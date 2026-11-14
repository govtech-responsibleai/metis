// The Targets of the API store, as the app shell reads them. Each Target has one Interview.

import type {
  InterviewState,
  LoadedInterviewRecord,
  StorageProblem,
} from "./transport/api.ts";
import { InterviewRepository } from "./storage/repository.ts";

export interface TargetSummary {
  id: string;
  title: string;
  updated: number;
}

export interface Target {
  id: string;
  title: string;
  // The Interview is done, so the Target has its Specification.
  done: boolean;
  interview: LoadedInterviewRecord;
}

export interface TargetList {
  targets: TargetSummary[];
  problems: readonly StorageProblem[];
}

// The Interview operations write through the same repository.
export const interviewRepository = new InterviewRepository();

export function interviewDone(state: InterviewState): boolean {
  return state.pending === null && state.confirmed;
}

export async function listTargets(): Promise<TargetList> {
  const targets = await interviewRepository.list();
  return { targets, problems: [...interviewRepository.problems] };
}

export async function readTarget(id: string): Promise<Target | undefined> {
  const interview = await interviewRepository.read(id);
  if (!interview) return undefined;
  return {
    id: interview.id,
    title: interview.title,
    done: interviewDone(interview.state),
    interview,
  };
}

export function deleteTarget(id: string): Promise<void> {
  return interviewRepository.delete(id);
}
