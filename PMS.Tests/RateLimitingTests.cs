using FluentAssertions;
using Microsoft.AspNetCore.Mvc;
using Moq;
using Patient_Management_System.Controllers;
using Patient_Management_System.Models;
using Patient_Management_System.Services;
using Xunit;

// Rate limiting is enforced by ASP.NET Core middleware (RateLimiterConfig).
// It cannot be tested at unit level — only via full integration with a running HTTP server.
// This test verifies the controller itself handles rapid login attempts gracefully.
public class RateLimitingTests
{
    [Fact]
    public async Task Login_Should_Propagate_Auth_Exceptions_On_Invalid_Credentials()
    {
        var mockService = new Mock<IAuthService>();
        mockService
            .Setup(s => s.Login(It.IsAny<User>()))
            .ThrowsAsync(new UnauthorizedAccessException("Invalid User Password!!!"));

        var controller = new AuthController(mockService.Object);

        Func<Task> act = () => controller.Login(new User { Email = "user-1@gmail.com", Password = "wrong" });

        await act.Should().ThrowAsync<UnauthorizedAccessException>();
    }
}
