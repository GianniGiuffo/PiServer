<?php

declare(strict_types=1);

namespace OCA\PublicShareDomain\AppInfo;

use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;
use OCP\AppFramework\Http\Events\BeforeTemplateRenderedEvent;
use OCP\EventDispatcher\IEventDispatcher;
use OCP\IUserSession;
use OCP\Util;

final class Application extends App implements IBootstrap
{
    public const APP_ID = 'public_share_domain';

    public function __construct(array $urlParams = [])
    {
        parent::__construct(self::APP_ID, $urlParams);
    }

    public function register(IRegistrationContext $context): void
    {
    }

    public function boot(IBootContext $context): void
    {
        $context->injectFn(function (
            IEventDispatcher $dispatcher,
            IUserSession $userSession,
        ): void {
            $dispatcher->addListener(
                BeforeTemplateRenderedEvent::class,
                static function () use ($userSession): void {
                    if ($userSession->isLoggedIn()) {
                        Util::addScript(self::APP_ID, 'public-share-domain');
                    }
                },
            );
        });
    }
}
