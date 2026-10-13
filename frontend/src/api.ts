export type Draft = {id: string; month: string; revision: number; note: string; created_at: string; updated_at: string};
export type Session = {token: string; data_dir: string; schema_version: number; stage: string};
export type History = {revision: number; kind: string; occurred_at: string};
export class ApiError extends Error {
  constructor(public code: string, message: string) {super(message)}
}
let token = '';
export function setToken(value: string) {token = value}
export async function upload<T>(path: string, file: File): Promise<T> {
  let response: Response;
  try {response = await fetch(`/api${path}`, {method:'POST', headers:{'Content-Type':'application/octet-stream','X-Session-Token':token},body:file,signal:AbortSignal.timeout(120000)})}
  catch {throw new ApiError('UPLOAD_CONNECTION','등록 결과를 확인하지 못했습니다. 최신 저장본을 불러오거나 같은 파일로 재시도해 주세요.')}
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.code ?? 'ERROR',data.message ?? '원본 등록에 실패했습니다.');
  return data as T;
}
export async function api<T>(path: string, method = 'GET', body?: unknown, timeout = 15000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {method, headers: {'Content-Type': 'application/json', 'X-Session-Token': token}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeout)});
  } catch {
    throw new ApiError('OFFLINE', '프로그램 연결이 끊겼습니다. 입력 내용은 남아 있습니다. 실행 상태를 확인한 뒤 다시 저장해 주세요.');
  }
  const data = await response.json().catch(() => {throw new ApiError('INVALID_RESPONSE', '프로그램 응답을 확인하지 못했습니다. 입력을 보존한 상태로 다시 시도해 주세요.')});
  if (!response.ok) throw new ApiError(data.code ?? 'ERROR', data.message ?? '요청을 처리하지 못했습니다.');
  return data as T;
}
