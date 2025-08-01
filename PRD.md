
# Product Requirements Document (PRD) for Nifty Shop UI/UX Overhaul

## 1. Overview

This document outlines the necessary UI/UX improvements to elevate the Nifty Shop application to a production-ready state. The current application is functional but lacks the polish, clarity, and user-centric design expected of a professional trading tool. The proposed changes focus on creating a more intuitive, informative, and visually appealing experience for the user.

## 2. Target Audience

The primary user of this application is an individual trader who needs a clear and concise interface to monitor their automated trading bot, review performance, and manage the system.

## 3. Key Goals

*   **Enhance Readability and Visual Hierarchy:** Improve the layout, typography, and use of space to make information easier to digest.
*   **Improve Navigation and User Flow:** Create a more intuitive and consistent navigation experience across the application.
*   **Increase Data Visualization:** Replace raw data tables with interactive charts and graphs to provide at-a-glance insights.
*   **Modernize the Look and Feel:** Update the visual design to be more modern, professional, and trustworthy.
*   **Improve User Feedback and Error Handling:** Provide clearer and more helpful feedback to the user, especially for actions and errors.

## 4. Proposed UI/UX Enhancements

### 4.1. Global Changes

*   **Consistent Navigation Bar:** The navigation bar should be consistent across all pages. The current implementation is good, but we can enhance it by highlighting the active page.
*   **Standardized Layout:** All pages should follow a consistent layout with a clear header, content area, and footer.
*   **Improved Typography:** Use a more modern and readable font stack. The current `Inter` font is a good choice, but we can improve the sizing and weight to create a better visual hierarchy.
*   **Color Palette Refinement:** The current color palette is a good starting point, but we can refine it to be more visually appealing and to use color more intentionally to convey meaning (e.g., green for profit, red for loss).
*   **Responsive Design:** Ensure the application is fully responsive and usable on a variety of screen sizes, from mobile phones to desktops.

### 4.2. Page-Specific Enhancements

#### 4.2.1. Login Page (`login.html`)

*   **Current State:** A basic login form.
*   **Proposed Changes:**
    *   Add a "Remember Me" checkbox for improved user convenience.
    *   Provide a "Forgot Password" link (this will require backend implementation).
    *   Improve the visual design with a more engaging layout, perhaps with a background image or a more prominent logo.

#### 4.2.2. Home/Dashboard Page (`index.html`)

*   **Current State:** A list of daily trading activity, with trades and logs hidden in collapsible sections.
*   **Proposed Changes:**
    *   **Dashboard-style Layout:** Instead of a simple list, create a dashboard with key metrics displayed prominently at the top (e.g., "Today's P&L", "Open Positions", "Recent Trades").
    *   **Interactive Charts:** Replace the tables of trades with interactive charts. For example, a bar chart showing daily P&L.
    *   **Improved Log Viewing:** The collapsible log section is a good start, but for better readability, we can use a modal or a dedicated log viewer with filtering and search capabilities.
    *   **Visual Trade Representation:** Instead of just text, use icons or colors to represent buy/sell actions and success/failure statuses.

#### 4.2.3. Performance Page (`performance.html`)

*   **Current State:** Tables for current positions and closed trades, with placeholders for charts.
*   **Proposed Changes:**
    *   **Implement Charts:** Replace the placeholders with actual, interactive charts:
        *   A pie chart showing the portfolio allocation by symbol.
        *   A line chart showing the cumulative profit/loss over time.
    *   **Key Performance Indicators (KPIs):** Display key performance metrics such as:
        *   Total P&L
        *   Win/Loss Ratio
        *   Average Winning Trade
        *   Average Losing Trade
    *   **Filtering and Sorting:** Allow the user to filter and sort the closed trades table by date, symbol, and P&L.

#### 4.2.4. Logs Page (`logs.html`)

*   **Current State:** A simple page that loads logs dynamically.
*   **Proposed Changes:**
    *   **Advanced Filtering:** Add options to filter logs by level (INFO, WARNING, ERROR), date range, and a search bar to search for specific messages.
    *   **Improved Readability:** Use a monospace font for log messages to improve readability, and color-code the log levels for quick scanning.
    *   **Log Highlighting:** Highlight important keywords or errors in the log messages.

#### 4.2.5. Token Refresh Page (`token_refresh.html`)

*   **Current State:** A page to manage the Fyers API token.
*   **Proposed Changes:**
    *   **Clearer Instructions:** Simplify the instructions for manual token generation. Use a step-by-step guide with screenshots or a short video tutorial.
    *   **Automated Token Refresh:** While the backend handles the refresh, the UI should provide clear feedback on the token status (e.g., "Token is valid for X hours", "Token is expired, attempting to refresh...").
    *   **Visual Timer:** Display a visual timer or progress bar indicating when the access token will expire.

#### 4.2.6. Strategy Page (`run_strategy.html`)

*   **Current State:** A page to manually run the trading strategy and view past runs.
*   **Proposed Changes:**
    *   **Real-time Feedback:** When a strategy is run manually, provide real-time feedback on its progress. This could be a log stream or a progress bar.
    *   **Detailed Run Information:** For each past run, provide more detailed information, such as the number of trades executed, the P&L for that run, and any errors that occurred.
    *   **Visual Status Indicators:** Use icons and colors to indicate the status of each run (e.g., success, failed, in progress).

## 5. Implementation Plan

The implementation of these changes can be broken down into the following phases:

1.  **Phase 1: Global Changes & Login Page:** Implement the consistent navigation, layout, typography, and color palette. Redesign the login page.
2.  **Phase 2: Dashboard & Performance Pages:** Redesign the home page as a dashboard and implement the interactive charts and KPIs on the performance page.
3.  **Phase 3: Logs & Token Refresh Pages:** Enhance the logs page with advanced filtering and improve the token refresh page with clearer instructions and feedback.
4.  **Phase 4: Strategy Page & Final Polish:** Redesign the strategy page and perform a final review of the entire application for consistency and polish.

By following this plan, we can systematically improve the UI/UX of the Nifty Shop application, resulting in a more professional, user-friendly, and production-ready product.
