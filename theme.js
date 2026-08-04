const fs = require("fs");
const path = require("path");

const SRC_DIR = path.join(__dirname, "admin-portal", "src");

function walk(dir, callback) {
  fs.readdirSync(dir).forEach(f => {
    let dirPath = path.join(dir, f);
    let isDirectory = fs.statSync(dirPath).isDirectory();
    isDirectory ? walk(dirPath, callback) : callback(path.join(dir, f));
  });
}

walk(SRC_DIR, (filePath) => {
  if (!filePath.endsWith(".tsx")) return;
  
  let content = fs.readFileSync(filePath, "utf-8");
  let modified = content;

  // Buttons (Primary)
  modified = modified.replace(/bg-blue-600/g, "bg-orange");
  modified = modified.replace(/hover:bg-blue-700/g, "hover:bg-orange-hover");
  modified = modified.replace(/ring-blue-700\/10/g, "ring-orange/10");
  
  // Table Headers
  modified = modified.replace(/text-gray-500 uppercase tracking-wider/g, "text-muted uppercase tracking-wider");

  // App Layout - Page Background
  if (filePath.endsWith("layout.tsx")) {
    modified = modified.replace(/bg-gray-50\/50/g, "bg-background");
    modified = modified.replace(/bg-gray-50\/30/g, "bg-background");
  }

  // Sidebar Updates
  if (filePath.endsWith("Sidebar.tsx")) {
    // Sidebar background
    modified = modified.replace(/bg-white/g, "bg-navy text-white");
    modified = modified.replace(/border-r/g, "border-navy-deep");
    // Logo icon
    modified = modified.replace(/text-blue-600 mr-2/g, "text-orange mr-2");
    // Nav links
    modified = modified.replace(/text-gray-700 hover:bg-gray-50 hover:text-blue-600/g, "text-gray-300 hover:bg-navy-deep hover:text-white");
    modified = modified.replace(/bg-gray-50 text-blue-600/g, "bg-navy-deep text-white");
    // Nav icons
    modified = modified.replace(/text-blue-600/g, "text-orange");
    modified = modified.replace(/text-gray-400 group-hover:text-blue-600/g, "text-gray-400 group-hover:text-white");
  }

  // Header Updates
  if (filePath.endsWith("Header.tsx")) {
    // Header background
    modified = modified.replace(/border-b bg-white/g, "border-b border-navy-deep bg-navy text-white");
    // Avatar
    modified = modified.replace(/text-blue-600/g, "text-accent");
    modified = modified.replace(/text-gray-700/g, "text-white");
    // Logout button
    modified = modified.replace(/text-gray-500 hover:bg-gray-50 hover:text-gray-900/g, "text-gray-300 hover:bg-navy-deep hover:text-white");
  }

  // Stat Cards Icon backgrounds
  // In page.tsx (Dashboard), bots/page.tsx, etc.
  modified = modified.replace(/bg-blue-50/g, "bg-info");
  modified = modified.replace(/bg-green-100/g, "bg-success");
  modified = modified.replace(/bg-orange-50/g, "bg-warning");
  modified = modified.replace(/bg-purple-50/g, "bg-warning");
  modified = modified.replace(/bg-yellow-50/g, "bg-warning");
  
  // Also we replace text colors inside stat cards if they are hardcoded blue-600, except button is orange now.
  // Wait, I already replaced blue-600 to orange globally.
  // In Dashboard (page.tsx): text-blue-600 was used for icons, now it's orange. Which is fine.
  
  // Text colors for headings
  modified = modified.replace(/text-gray-900/g, "text-navy");
  modified = modified.replace(/text-gray-800/g, "text-navy-deep");

  // Inputs and borders
  modified = modified.replace(/border-blue-600/g, "border-orange");
  modified = modified.replace(/border-blue-500/g, "border-orange");
  modified = modified.replace(/focus:border-blue-500/g, "focus:border-orange");
  modified = modified.replace(/focus:ring-blue-500/g, "focus:ring-orange");

  if (content !== modified) {
    fs.writeFileSync(filePath, modified, "utf-8");
    console.log("Updated: " + filePath);
  }
});
