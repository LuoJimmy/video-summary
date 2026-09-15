export type PagerItem =
  { type: "page"; value: number } | { type: "ellipsis"; jump: number };

const BUFFER = 2;
const JUMP = 5;

export function pagerItems(current: number, totalPages: number): PagerItem[] {
  const allPages = Math.max(1, Math.floor(totalPages) || 1);
  const page = Math.min(allPages, Math.max(1, Math.floor(current) || 1));
  const items: PagerItem[] = [];

  if (allPages <= 3 + BUFFER * 2) {
    for (let i = 1; i <= allPages; i += 1) {
      items.push({ type: "page", value: i });
    }
    return items;
  }

  let left = Math.max(1, page - BUFFER);
  let right = Math.min(page + BUFFER, allPages);
  if (page - 1 <= BUFFER) {
    right = 1 + BUFFER * 2;
  }
  if (allPages - page <= BUFFER) {
    left = allPages - BUFFER * 2;
  }

  for (let i = left; i <= right; i += 1) {
    items.push({ type: "page", value: i });
  }

  if (page - 1 >= BUFFER * 2 && page !== 1 + 2) {
    items.unshift({
      type: "ellipsis",
      jump: Math.max(1, page - JUMP),
    });
  }
  if (allPages - page >= BUFFER * 2 && page !== allPages - 2) {
    items.push({
      type: "ellipsis",
      jump: Math.min(allPages, page + JUMP),
    });
  }

  if (left !== 1) {
    items.unshift({ type: "page", value: 1 });
  }
  if (right !== allPages) {
    items.push({ type: "page", value: allPages });
  }

  return items;
}

export function pageAfterSizeChange(
  page: number,
  pageSize: number,
  nextSize: number
): number {
  const size = Math.max(1, Math.floor(nextSize) || 1);
  const first = Math.max(0, (Math.max(1, page) - 1) * Math.max(1, pageSize));
  return Math.floor(first / size) + 1;
}
