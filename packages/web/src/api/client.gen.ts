/**
 * Bonbon API
 * 0.1.0
 * DO NOT MODIFY - This file has been generated using oazapfts.
 * See https://www.npmjs.com/package/oazapfts
 */
import * as Oazapfts from "@oazapfts/runtime";
import * as QS from "@oazapfts/runtime/query";
export const defaults: Oazapfts.Defaults<Oazapfts.CustomHeaders> = {
    headers: {},
    baseUrl: "/"
};
const oazapfts = Oazapfts.runtime(defaults);
export const servers = {
    server1: "/"
};
export type Household = {
    id: string;
    name: string;
    created_at: string;
    my_role: MyRole;
};
export type ValidationError = {
    loc: (string | number)[];
    "type": string;
};
export type HttpValidationError = {
    detail?: ValidationError[];
};
export type Member = {
    user_id: string;
    display_name: string;
    role: Role;
    joined_at: string;
};
export type MemberList = {
    members: Member[];
};
export type InviteCode = {
    code: string;
    expires_at: string;
};
export type TransferOwnerRequest = {
    user_id: string;
};
export type ReceiptSummary = {
    id: string;
    status: Status;
    store: string | null;
    purchase_date: string | null;
    total_rappen: number | null;
    uploaded_by_name: string | null;
    created_at: string;
    possible_duplicate: boolean;
};
export type ReceiptList = {
    receipts: ReceiptSummary[];
};
export type CreateReceiptRequest = {
    content_type: ContentType;
    size_bytes: number;
};
export type ReceiptUpload = {
    receipt_id: string;
    upload_url: string;
    upload_headers: {
        [key: string]: string;
    };
    expires_in: number;
};
export type ReceiptItem = {
    position: number;
    name: string;
    quantity: number;
    unit_price_rappen: number | null;
    amount_rappen: number;
    category: string;
};
export type ReceiptDetail = {
    id: string;
    status: Status;
    store: string | null;
    purchase_date: string | null;
    total_rappen: number | null;
    uploaded_by_name: string | null;
    created_at: string;
    possible_duplicate: boolean;
    image_url: string;
    items: ReceiptItem[];
};
export type ItemCorrection = {
    position: number;
    name: string;
    quantity: number;
    unit_price_rappen?: number | null;
    amount_rappen: number;
    category: string;
};
export type ReceiptCorrection = {
    store?: string | null;
    purchase_date?: string | null;
    total_rappen?: number | null;
    items?: ItemCorrection[] | null;
};
export type CategoryTotal = {
    category: string;
    total_rappen: number;
};
export type StoreTotal = {
    store: string | null;
    total_rappen: number;
};
export type MonthlyReport = {
    month: string;
    total_rappen: number;
    receipt_count: number;
    previous_month_total_rappen: number;
    by_category: CategoryTotal[];
    by_store: StoreTotal[];
};
export type MonthTotal = {
    month: string;
    total_rappen: number;
};
export type SpendingTrend = {
    months: MonthTotal[];
};
export type HouseholdList = {
    households: Household[];
};
export type CreateHouseholdRequest = {
    name: string;
};
export type JoinRequest = {
    code: string;
};
export type CategoryList = {
    categories: string[];
};
/**
 * GET /households/{household_id}
 */
export function getHousehold({ householdId }: {
    householdId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: Household;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}`, {
        ...opts
    }));
}
/**
 * GET /households/{household_id}/members
 */
export function listMembers({ householdId }: {
    householdId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: MemberList;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/members`, {
        ...opts
    }));
}
/**
 * POST /households/{household_id}/invites
 */
export function createInvite({ householdId }: {
    householdId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 201;
        data: InviteCode;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/invites`, {
        ...opts,
        method: "POST"
    }));
}
/**
 * DELETE /households/{household_id}/members/me
 */
export function leaveHousehold({ householdId }: {
    householdId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 204;
        data: null;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 409;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/members/me`, {
        ...opts,
        method: "DELETE"
    }));
}
/**
 * DELETE /households/{household_id}/members/{user_id}
 */
export function removeMember({ householdId, userId }: {
    householdId: string;
    userId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 204;
        data: null;
    } | {
        status: 403;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 409;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/members/${encodeURIComponent(userId)}`, {
        ...opts,
        method: "DELETE"
    }));
}
/**
 * PUT /households/{household_id}/owner
 */
export function transferOwnership({ householdId, transferOwnerRequest }: {
    householdId: string;
    transferOwnerRequest: TransferOwnerRequest;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: MemberList;
    } | {
        status: 403;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/owner`, oazapfts.json({
        ...opts,
        method: "PUT",
        body: transferOwnerRequest
    })));
}
/**
 * GET /households/{household_id}/receipts
 */
export function listReceipts({ householdId, month }: {
    householdId: string;
    month?: string | null;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: ReceiptList;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts${QS.query(QS.explode({
        month
    }))}`, {
        ...opts
    }));
}
/**
 * POST /households/{household_id}/receipts
 */
export function createReceipt({ householdId, createReceiptRequest }: {
    householdId: string;
    createReceiptRequest: CreateReceiptRequest;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 201;
        data: ReceiptUpload;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts`, oazapfts.json({
        ...opts,
        method: "POST",
        body: createReceiptRequest
    })));
}
/**
 * GET /households/{household_id}/receipts/{receipt_id}
 */
export function getReceipt({ householdId, receiptId }: {
    householdId: string;
    receiptId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: ReceiptDetail;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts/${encodeURIComponent(receiptId)}`, {
        ...opts
    }));
}
/**
 * PATCH /households/{household_id}/receipts/{receipt_id}
 */
export function updateReceipt({ householdId, receiptId, receiptCorrection }: {
    householdId: string;
    receiptId: string;
    receiptCorrection: ReceiptCorrection;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: ReceiptDetail;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 409;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts/${encodeURIComponent(receiptId)}`, oazapfts.json({
        ...opts,
        method: "PATCH",
        body: receiptCorrection
    })));
}
/**
 * GET /households/{household_id}/reports/monthly
 */
export function getMonthlyReport({ householdId, month }: {
    householdId: string;
    month: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: MonthlyReport;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/reports/monthly${QS.query(QS.explode({
        month
    }))}`, {
        ...opts
    }));
}
/**
 * GET /households/{household_id}/reports/trend
 */
export function getSpendingTrend({ householdId, months }: {
    householdId: string;
    months?: number;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: SpendingTrend;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/reports/trend${QS.query(QS.explode({
        months
    }))}`, {
        ...opts
    }));
}
/**
 * GET /households
 */
export function listHouseholds(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: HouseholdList;
    } | {
        status: 422;
        data: HttpValidationError;
    }>("/households", {
        ...opts
    }));
}
/**
 * POST /households
 */
export function createHousehold({ createHouseholdRequest }: {
    createHouseholdRequest: CreateHouseholdRequest;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: Household;
    } | {
        status: 422;
        data: HttpValidationError;
    }>("/households", oazapfts.json({
        ...opts,
        method: "POST",
        body: createHouseholdRequest
    })));
}
/**
 * POST /households/join
 */
export function joinHousehold({ joinRequest }: {
    joinRequest: JoinRequest;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: Household;
    } | {
        status: 404;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 409;
        data: {
            statusCode: number;
            message: string;
        };
    } | {
        status: 422;
        data: HttpValidationError;
    } | {
        status: 429;
        data: {
            statusCode: number;
            message: string;
        };
    }>("/households/join", oazapfts.json({
        ...opts,
        method: "POST",
        body: joinRequest
    })));
}
/**
 * GET /categories
 */
export function listCategories(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: CategoryList;
    } | {
        status: 422;
        data: HttpValidationError;
    }>("/categories", {
        ...opts
    }));
}
/**
 * DELETE /users/me
 */
export function deleteAccount(opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 202;
        data: null;
    } | {
        status: 422;
        data: HttpValidationError;
    }>("/users/me", {
        ...opts,
        method: "DELETE"
    }));
}
export enum MyRole {
    Owner = "owner",
    Member = "member"
}
export enum Role {
    Owner = "owner",
    Member = "member"
}
export enum Status {
    Uploaded = "uploaded",
    Done = "done",
    Failed = "failed",
    Duplicate = "duplicate"
}
export enum ContentType {
    ImageJpeg = "image/jpeg",
    ImagePng = "image/png",
    ApplicationPdf = "application/pdf"
}
