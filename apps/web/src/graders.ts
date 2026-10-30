import type { Specification } from "./transport/api";

export function specificationHasCriteria(
  specification: Specification,
): boolean {
  return specification.features.some((feature) =>
    feature.behaviours.some((behaviour) => behaviour.criteria.length > 0),
  );
}
