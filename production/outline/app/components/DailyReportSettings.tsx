import { observer } from "mobx-react";
import { useState } from "react";
import { toast } from "sonner";
import styled from "styled-components";
import { s } from "@shared/styles";
import {
  DailyReportMode,
  DocumentPreference,
  TeamPreference,
} from "@shared/types";
import { errToString } from "@shared/utils/error";
import { normalizeDailyReportMode } from "@shared/utils/dailyReport";
import useCurrentTeam from "~/hooks/useCurrentTeam";
import usePolicy from "~/hooks/usePolicy";
import type Document from "~/models/Document";
import Switch from "./Switch";

/** Saves the administrator's workspace-wide master switch using the existing team settings API. */
export const DailyReportWorkspaceSwitch = observer(
  function DailyReportWorkspaceSwitch() {
    const team = useCurrentTeam();
    const can = usePolicy(team);
    const [saving, setSaving] = useState(false);
    const handleChange = async (checked: boolean) => {
      if (!can.update || saving) {
        return;
      }
      setSaving(true);
      try {
        await team.save({
          preferences: { [TeamPreference.DailyReports]: checked },
        });
        toast.success("업무보고 도구 설정을 저장했습니다.");
      } catch (error) {
        toast.error(errToString(error));
      } finally {
        setSaving(false);
      }
    };
    return (
      <Switch
        id={TeamPreference.DailyReports}
        name={TeamPreference.DailyReports}
        aria-label="업무보고 도구 사용"
        checked={team.getPreference(TeamPreference.DailyReports)}
        disabled={!can.update || saving}
        onChange={(checked) => void handleChange(checked)}
      />
    );
  }
);

/** Renders the document's persistent report mode; the workspace master switch takes precedence. */
export const DailyReportDocumentSetting = observer(
  function DailyReportDocumentSetting({ document }: { document: Document }) {
    const team = useCurrentTeam();
    const can = usePolicy(document);
    const [saving, setSaving] = useState(false);
    const workspaceEnabled = team.getPreference(TeamPreference.DailyReports);
    const handleChange = async (checked: boolean) => {
      if (!workspaceEnabled || !can.update || saving) {
        return;
      }
      setSaving(true);
      try {
        await document.save({
          preferences: {
            [DocumentPreference.DailyReportTools]: checked
              ? DailyReportMode.On
              : DailyReportMode.Off,
          },
        });
        toast.success("이 문서의 업무보고 도구 설정을 저장했습니다.");
      } catch (error) {
        toast.error(errToString(error));
      } finally {
        setSaving(false);
      }
    };
    return (
      <DocumentSetting>
        <ToggleMenuItem
          id={`${document.id}-daily-report-tools`}
          name={DocumentPreference.DailyReportTools}
          aria-label="문서별 업무보고 도구"
          label="업무보고 도구"
          labelPosition="left"
          width={26}
          height={14}
          checked={
            normalizeDailyReportMode(
              document.getPreference(DocumentPreference.DailyReportTools)
            ) === DailyReportMode.On
          }
          disabled={!workspaceEnabled || !can.update || saving}
          onChange={(checked) => void handleChange(checked)}
        />
        {!workspaceEnabled && (
          <small>워크스페이스 설정에서 꺼져 있습니다.</small>
        )}
      </DocumentSetting>
    );
  }
);

const DocumentSetting = styled.div`
  small {
    color: ${s("textSecondary")};
    display: block;
    padding-top: 6px;
  }
`;

const ToggleMenuItem = styled(Switch)`
  * {
    font-weight: normal;
    color: ${s("textSecondary")};
  }
`;
