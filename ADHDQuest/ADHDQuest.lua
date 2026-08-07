-- ADHDQuest
-- Captures quest text and replaces the description shown in the quest
-- window with a cached short summary, with a button to expand back to
-- the original.
-- Summaries are produced OUT OF GAME by a companion script (see companion.py)
-- because addons can't make network calls. This file only reads/writes
-- its own SavedVariables and touches the quest frame's own text widget.

ADHDQuest_Cache = ADHDQuest_Cache or {}                     -- key -> summary string (grown live by companion.py)
ADHDQuest_Pending = ADHDQuest_Pending or {}                 -- key -> { title, text, id }
ADHDQuest_StaticSummaries = ADHDQuest_StaticSummaries or {} -- key -> summary string (baked in by pregenerate.py)

-- Build a stable key: prefer the numeric quest ID when the client exposes one,
-- otherwise fall back to a title+text fingerprint (needed on older/private-server
-- clients, and safer anyway since some quest text varies by class/race/faction).
local function MakeKey(id, title, text)
    if id and id ~= 0 then
        return "id:" .. tostring(id)
    end
    local snippet = (text or ""):sub(1, 80)
    return "txt:" .. (title or "") .. "|" .. snippet
end

----------------------------------------------------------------------
-- In-place display: overwrites QuestInfoDescriptionText (the flavor-text
-- widget Blizzard reuses across the detail/progress/reward quest pages)
-- with the short version, plus a small toggle button below it.
----------------------------------------------------------------------

local toggleBtn = CreateFrame("Button", "ADHDQuestToggleBtn", QuestFrame, "UIPanelButtonTemplate")
toggleBtn:SetSize(120, 20)
toggleBtn:SetText("Show full text")
toggleBtn:Hide()

local showingFull, currentSummary, currentFull = false, "", ""

local function Refresh()
    local widget = _G["QuestInfoDescriptionText"]
    if not widget then return end
    widget:SetText(showingFull and currentFull or currentSummary)
    toggleBtn:SetText(showingFull and "Show summary" or "Show full text")
    toggleBtn:ClearAllPoints()
    toggleBtn:SetPoint("TOPLEFT", widget, "BOTTOMLEFT", 0, -6)
    toggleBtn:Show()
end

toggleBtn:SetScript("OnClick", function()
    showingFull = not showingFull
    Refresh()
end)

local function ShowInPlace(summary, fullText)
    currentSummary, currentFull = summary, fullText
    showingFull = false
    Refresh()
end

----------------------------------------------------------------------
-- Capture
----------------------------------------------------------------------

local function Capture(text, questTitle, id)
    if not text or text == "" then return end
    local key = MakeKey(id, questTitle, text)

    local summary = ADHDQuest_Cache[key] or ADHDQuest_StaticSummaries[key]
    if summary then
        local widget = _G["QuestInfoDescriptionText"]
        if widget then
            ShowInPlace(summary, text)
        else
            print("|cff33ff99[TL;DR]|r " .. summary) -- fallback if this client's frame differs
        end
    else
        toggleBtn:Hide()
        if not ADHDQuest_Pending[key] then
            local objectivesWidget = _G["QuestInfoObjectivesText"]
            local objectives = objectivesWidget and objectivesWidget:GetText() or nil
            ADHDQuest_Pending[key] = { title = questTitle, text = text, objectives = objectives, id = id }
        end
    end
end

local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("QUEST_DETAIL")
f:RegisterEvent("QUEST_PROGRESS")
f:RegisterEvent("QUEST_COMPLETE")
f:RegisterEvent("QUEST_FINISHED")
f:SetScript("OnEvent", function(_, event, addonName)
    if event == "ADDON_LOADED" then
        if addonName == "ADHDQuest" then
            print("|cff33ff99ADHDQuest|r loaded. Open a quest, then /adhdquest to check status.")
        end
        return
    elseif event == "QUEST_FINISHED" then
        toggleBtn:Hide()
        return
    end

    local id = (GetQuestID and GetQuestID()) or nil
    local questTitle = (GetTitleText and GetTitleText()) or nil

    if event == "QUEST_DETAIL" and GetQuestText then
        Capture(GetQuestText(), questTitle, id)
    elseif event == "QUEST_PROGRESS" and GetProgressText then
        Capture(GetProgressText(), questTitle, id)
    elseif event == "QUEST_COMPLETE" and GetRewardText then
        Capture(GetRewardText(), questTitle, id)
    end
end)

SLASH_ADHDQUEST1 = "/adhdquest"
SlashCmdList["ADHDQUEST"] = function()
    local pending, cached = 0, 0
    for _ in pairs(ADHDQuest_Pending) do pending = pending + 1 end
    for _ in pairs(ADHDQuest_Cache) do cached = cached + 1 end
    print(("ADHDQuest: %d cached, %d waiting to be summarized. Run companion.py and log out/in to sync."):format(cached, pending))
end
