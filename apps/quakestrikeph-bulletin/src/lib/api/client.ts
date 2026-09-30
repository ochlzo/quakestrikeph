import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const bulletinApi = createClient<paths>({ baseUrl: "/api/v1" });
