using System.Net;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc;
using Moq;
using Patient_Management_System.Controllers;
using Patient_Management_System.Models;
using Patient_Management_System.Services;
using Xunit;

public class AuthTests
{
    [Fact]
    public async Task Login_Returns_Token_When_Credentials_Are_Valid()
    {
        var mockService = new Mock<IAuthService>();
        mockService
            .Setup(s => s.Login(It.IsAny<User>()))
            .ReturnsAsync("fake-jwt-token");

        var controller = new AuthController(mockService.Object);
        var result = await controller.Login(new User { Email = "user-1@gmail.com", Password = "PMS" });

        result.Should().BeOfType<OkObjectResult>();
        (result as OkObjectResult)!.StatusCode.Should().Be(200);
    }

    [Fact]
    public async Task Login_Should_Return_Unauthorized_For_Invalid_Password()
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
