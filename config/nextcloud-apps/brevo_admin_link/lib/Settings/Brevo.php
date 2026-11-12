<?php

declare(strict_types=1);

namespace OCA\BrevoAdminLink\Settings;

use OCP\AppFramework\Http\TemplateResponse;
use OCP\IURLGenerator;
use OCP\Settings\IIconSection;
use OCP\Settings\ISettings;

final class Brevo implements IIconSection, ISettings {
    public function __construct(private IURLGenerator $urls) {
    }

    public function getID(): string {
        return 'brevo_admin_link';
    }

    public function getName(): string {
        return 'Brevo';
    }

    public function getPriority(): int {
        return 99;
    }

    public function getIcon(): string {
        return $this->urls->imagePath('core', 'actions/external.svg');
    }

    public function getForm(): TemplateResponse {
        return new TemplateResponse($this->getID(), 'admin', [], TemplateResponse::RENDER_AS_BLANK);
    }

    public function getSection(): string {
        return $this->getID();
    }
}
