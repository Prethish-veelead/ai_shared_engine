"use client";

import { useEffect, useState } from "react";
import { api, UserAnalytics } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { formatDistanceToNow } from "date-fns";

export default function UsersPage() {
  const [users, setUsers] = useState<UserAnalytics[]>([]);
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const data = await api.getUserAnalytics();
        setUsers(data);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady]);

  if (loading) return <div className="flex h-full items-center justify-center">Loading users...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy">User Analytics</h1>
          <p className="text-sm text-gray-500">View activity across your user base.</p>
        </div>
      </div>

      <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">User</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Last Login</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Questions Asked</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Tokens Used</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {users.map((user) => (
              <tr key={user.user_id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-navy">{user.email}</div>
                  <div className="text-sm text-gray-500">{user.user_id}</div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {user.last_login ? formatDistanceToNow(new Date(user.last_login), { addSuffix: true }) : "—"}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-navy text-right">
                  {user.questions_asked.toLocaleString()}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                  {user.tokens_used.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
