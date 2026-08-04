"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Bot,
  BarChart3,
  DollarSign,
  Users,
  MessageSquareText,
  Activity,
  Sparkles,
  ChevronLeft
} from "lucide-react";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Assistant", href: "/assistant", icon: Sparkles },
  { name: "Bot Management", href: "/bots", icon: Bot },
  { name: "Usage", href: "/usage", icon: BarChart3 },
  { name: "Cost", href: "/cost", icon: DollarSign },
  { name: "User Analytics", href: "/users", icon: Users },
  { name: "Chat History", href: "/history", icon: MessageSquareText },
  { name: "Logs & Monitoring", href: "/logs", icon: Activity },
];

export function Sidebar() {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <div 
      className={cn(
        "flex h-full flex-col bg-navy/95 backdrop-blur-md shadow-2xl text-white border-r border-navy-deep/50 overflow-hidden z-20 transition-all duration-300 ease-in-out",
        isCollapsed ? "w-20" : "w-64"
      )}
    >
      <div 
        className={cn(
          "flex h-20 shrink-0 items-center border-b border-navy-deep/50 bg-navy/30 transition-all duration-300",
          isCollapsed ? "justify-center cursor-pointer hover:bg-navy-deep/50" : "px-5 justify-between"
        )}
        onClick={isCollapsed ? () => setIsCollapsed(false) : undefined}
        title={isCollapsed ? "Expand Sidebar" : undefined}
      >
        <div className="flex items-center">
          <div className="flex items-center justify-center bg-white rounded-lg w-10 h-10 shadow-md shrink-0">
            <span className="text-2xl font-black tracking-tighter text-navy leading-none">V</span>
            <span className="text-2xl font-black tracking-tighter text-orange leading-none -ml-0.5">L</span>
          </div>
          {!isCollapsed && <span className="ml-3 text-lg font-bold tracking-tight text-white whitespace-nowrap">Admin Portal</span>}
        </div>
        {!isCollapsed && (
          <button 
            onClick={() => setIsCollapsed(true)} 
            className="text-gray-400 hover:text-white p-1 rounded-md hover:bg-navy-deep transition-colors shrink-0"
            title="Collapse Sidebar"
          >
            <ChevronLeft size={18} />
          </button>
        )}
      </div>
      <div className="flex flex-1 flex-col overflow-y-auto pt-4 no-scrollbar">
        <nav className={cn("flex-1 space-y-1", isCollapsed ? "px-2" : "px-3")}>
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                title={isCollapsed ? item.name : undefined}
                className={cn(
                  isActive
                    ? "bg-navy-deep text-white shadow-sm"
                    : "text-gray-300 hover:bg-navy-deep/50 hover:text-white hover:translate-x-1",
                  "group relative flex items-center rounded-md font-medium transition-all duration-300 ease-out",
                  isCollapsed ? "justify-center px-0 py-3" : "px-3 py-2 text-sm"
                )}
              >
                {/* Vertical Active Pill Indicator */}
                {isActive && (
                  <div className="absolute left-0 top-1/2 h-2/3 w-1 -translate-y-1/2 rounded-r-md bg-orange" />
                )}
                
                <item.icon
                  className={cn(
                    isActive ? "text-orange" : "text-gray-400 group-hover:text-orange group-hover:scale-110",
                    "h-5 w-5 flex-shrink-0 transition-all duration-300 ease-out",
                    isCollapsed ? "mr-0" : "mr-3"
                  )}
                  aria-hidden="true"
                />
                {!isCollapsed && <span className="whitespace-nowrap overflow-hidden">{item.name}</span>}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
